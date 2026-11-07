from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST
from .dav import allow_web_change
from .disk import DiskError, Pending, exclusive, filename, locate, remove, tally


@login_required
@require_GET
def files(request):
    user = request.user
    relative = request.GET.get('p','')
    try:
        folder = locate(user, relative)
        entries = []
        for path in folder.iterdir():
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            entries.append((path.name, path.is_dir(), stat.st_size, path.relative_to(user.folder).as_posix()))
    except (DiskError, OSError) as exc:
        raise Http404 from exc
    entries.sort(key=lambda item: (not item[1], item[0].casefold()))
    parent = relative.rpartition('/')[0]
    return render(request, 'files.html', {'entries': entries, 'path': relative, 'parent': parent,
                                          'dav': request.build_absolute_uri('/dav/')})


@login_required
@require_POST
def change(request):
    user = request.user
    relative = request.POST.get('p','')
    try:
        with exclusive(user):
            folder = locate(user, relative)
            if not folder.is_dir():
                raise DiskError('Папка недоступна.')
            action = request.POST.get('action')
            if action == 'upload':
                uploads = request.FILES.getlist('file')
                if not uploads:
                    raise DiskError('Выберите файл.')
                for upload in uploads:
                    target = locate(user, (folder/filename(upload.name)).relative_to(user.folder).as_posix())
                    allow_web_change(user, target, membership=not target.exists())
                    pending = Pending(user, target)
                    try:
                        for chunk in upload.chunks():
                            pending.write(chunk)
                    except BaseException:
                        pending.finish(False)
                        raise
                    pending.finish(True)
            else:
                name = filename(request.POST.get('name',''))
                target = locate(user, (folder/name).relative_to(user.folder).as_posix())
                allow_web_change(user, target, membership=True)
                if action == 'mkdir':
                    target.mkdir()
                elif action == 'delete':
                    remove(target)
                elif action == 'rename':
                    dest = folder/filename(request.POST.get('to',''))
                    if dest.exists() or dest.is_symlink():
                        raise DiskError('Имя занято.')
                    target.rename(dest)
                else:
                    raise DiskError('Неизвестная операция.')
    except DiskError as exc:
        messages.error(request, str(exc))
    except OSError:
        messages.error(request, 'Операция не выполнена. Проверьте имя, доступное место и содержимое папки.')
    return redirect('/?' + urlencode({'p': relative}))


@login_required
@require_GET
def download(request):
    try:
        path = locate(request.user, request.GET.get('p',''))
        return FileResponse(path.open('rb'), as_attachment=True, filename=path.name)
    except (DiskError, OSError) as exc:
        raise Http404 from exc


@login_required
@require_GET
def stats(request):
    groups = tally(request.user.folder)
    used = sum(row[1] for row in groups.values())
    rows = [(ext, count, size, round(100*size/used) if used else 0)
            for ext, (count, size) in groups.items()]
    rows.sort(key=lambda row: (-row[2], row[0]))
    return render(request, 'stats.html', {'rows': rows, 'used': used,
                  'quota': request.user.quota_mib*1024**2, 'count': sum(r[1] for r in rows)})
