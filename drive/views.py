"""Session/CSRF-protected Django file manager views."""
from datetime import datetime
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from .storage import (QuotaExceeded, UnsafePath, mutation_lock, quota_bytes,
                      safe_user_path, sum_bytes, file_statistics, validate_name, root_for_user_id)
from django.conf import settings


def go_to(relative=''):
    url = '/'
    if relative:
        url += '?' + urlencode({'path': relative})
    return redirect(url)


def relative_or_empty(request, method='GET', field='path'):
    return (request.GET if method == 'GET' else request.POST).get(field, '').strip('/')


@login_required
def browse(request):
    relative = relative_or_empty(request)
    try:
        current = safe_user_path(request.user.pk, relative)
        if not current.is_dir():
            raise UnsafePath('Папка не существует.')
    except (UnsafePath, OSError):
        messages.error(request, 'Указанная папка недоступна.')
        return go_to()

    items = []
    for entry in current.iterdir():
        if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
            continue
        stat = entry.stat()
        rel = '/'.join(part for part in [relative, entry.name] if part)
        items.append({
            'name': entry.name, 'rel': rel, 'folder': entry.is_dir(),
            'size': None if entry.is_dir() else stat.st_size,
            'changed': datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
        })
    items.sort(key=lambda i: (not i['folder'], i['name'].casefold()))
    used = sum_bytes(root_for_user_id(request.user.pk))
    limit = quota_bytes(request.user.pk)
    breadcrumbs = [{'name': 'Мои файлы', 'rel': ''}]
    prefix = ''
    for seg in [p for p in relative.split('/') if p]:
        prefix = f'{prefix}/{seg}'.strip('/')
        breadcrumbs.append({'name': seg, 'rel': prefix})
    return render(request, 'drive/index.html', {
        'items': items, 'relative': relative, 'breadcrumbs': breadcrumbs,
        'used': used, 'limit': limit, 'percent': min(100, round(used * 100 / limit)) if limit else 100,
        'dav_url': request.build_absolute_uri('/dav/'),
    })


@login_required
@require_POST
def upload(request):
    relative = relative_or_empty(request, 'POST')
    files = request.FILES.getlist('files')
    if not files:
        messages.error(request, 'Выберите хотя бы один файл.')
        return go_to(relative)
    try:
        with mutation_lock(request.user.pk):
            folder = safe_user_path(request.user.pk, relative)
            if not folder.is_dir():
                raise UnsafePath('Папка не существует.')
            settings.POLKA_STAGING_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
            used = sum_bytes(root_for_user_id(request.user.pk))
            limit = quota_bytes(request.user.pk)
            completed = 0
            for upload_file in files:
                name = validate_name(upload_file.name)
                destination = safe_user_path(request.user.pk, '/'.join(filter(None, [relative, name])))
                if destination.is_dir():
                    raise UnsafePath('Файл конфликтует с существующей папкой.')
                previous = destination.stat().st_size if destination.exists() else 0
                if used - previous + upload_file.size > limit:
                    raise QuotaExceeded(f'Для файла «{name}» превышена квота.')
                staged = None
                try:
                    with tempfile.NamedTemporaryFile(dir=settings.POLKA_STAGING_ROOT,
                                                      prefix='web-', delete=False) as handle:
                        staged = Path(handle.name)
                        for chunk in upload_file.chunks():
                            handle.write(chunk)
                    os.replace(staged, destination)
                    staged = None
                    used = used - previous + upload_file.size
                    completed += 1
                finally:
                    if staged is not None:
                        staged.unlink(missing_ok=True)
            if completed:
                messages.success(request, f'Загружено файлов: {completed}.')
    except (QuotaExceeded, UnsafePath, OSError) as exc:
        messages.error(request, str(exc))
    return go_to(relative)


@login_required
@require_POST
def create_folder(request):
    relative = relative_or_empty(request, 'POST')
    try:
        with mutation_lock(request.user.pk):
            parent = safe_user_path(request.user.pk, relative)
            if not parent.is_dir():
                raise UnsafePath('Родительская папка не найдена.')
            name = validate_name(request.POST.get('name', '').strip())
            target = safe_user_path(request.user.pk, '/'.join(filter(None, [relative, name])))
            target.mkdir()
            messages.success(request, f'Папка «{name}» создана.')
    except (UnsafePath, OSError) as exc:
        messages.error(request, str(exc))
    return go_to(relative)


@login_required
@require_POST
def rename(request):
    relative = relative_or_empty(request, 'POST', 'current')
    parent = str(Path(relative).parent).replace('\\', '/')
    if parent == '.':
        parent = ''
    try:
        with mutation_lock(request.user.pk):
            src = safe_user_path(request.user.pk, relative)
            if not relative or not src.exists():
                raise UnsafePath('Файл или папка не найдены.')
            name = validate_name(request.POST.get('new_name', '').strip())
            dest = safe_user_path(request.user.pk, '/'.join(filter(None, [parent, name])))
            if dest.exists():
                raise UnsafePath('Имя уже занято.')
            src.rename(dest)
            messages.success(request, 'Название изменено.')
    except (UnsafePath, OSError) as exc:
        messages.error(request, str(exc))
    return go_to(parent)


@login_required
@require_POST
def delete(request):
    relative = relative_or_empty(request, 'POST', 'current')
    parent = str(Path(relative).parent).replace('\\', '/')
    if parent == '.':
        parent = ''
    try:
        with mutation_lock(request.user.pk):
            target = safe_user_path(request.user.pk, relative)
            if not relative or not target.exists():
                raise UnsafePath('Удаление корня запрещено или файл не найден.')
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            messages.success(request, 'Объект удалён.')
    except (UnsafePath, OSError) as exc:
        messages.error(request, str(exc))
    return go_to(parent)


@login_required
def download(request):
    relative = relative_or_empty(request)
    try:
        path = safe_user_path(request.user.pk, relative)
        if not path.is_file() or not relative:
            raise Http404
        return FileResponse(path.open('rb'), as_attachment=True, filename=path.name)
    except (OSError, UnsafePath):
        raise Http404


@login_required
def statistics(request):
    groups = file_statistics(root_for_user_id(request.user.pk))
    used = sum(row['size'] for row in groups)
    for group in groups:
        group['percent'] = round(group['size'] * 100 / used) if used else 0
    return render(request, 'drive/statistics.html', {
        'groups': groups, 'used': used, 'limit': quota_bytes(request.user.pk),
        'count': sum(row['count'] for row in groups),
    })
