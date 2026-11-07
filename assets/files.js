const checkboxes = [...document.querySelectorAll('.row-check')];
const all = document.querySelector('#select-all');
const removeButton = document.querySelector('#remove-selected');
const deletion = document.querySelector('#delete-dialog');
const renaming = document.querySelector('#rename-dialog');

function selected() {
  return checkboxes.filter(box => box.checked);
}

function syncSelection() {
  if (!all) return;
  const count = selected().length;
  all.checked = count === checkboxes.length;
  all.indeterminate = count > 0 && !all.checked;
  removeButton.disabled = count === 0;
  document.querySelector('#counter').textContent = count ? 'Выбрано: ' + count : '';
}

all?.addEventListener('change', () => {
  for (const box of checkboxes) box.checked = all.checked;
  syncSelection();
});
for (const box of checkboxes) box.addEventListener('change', syncSelection);
window.addEventListener('pageshow', syncSelection);
removeButton?.addEventListener('click', () => {
  const boxes = selected();
  if (!boxes.length) return;
  const names = boxes.map(box => box.value);
  deletion.querySelector('[name=selection]').value = JSON.stringify(names);
  deletion.querySelector('#delete-summary').textContent = 'Объектов к удалению: ' + names.length + '. Это действие необратимо.';
  deletion.querySelector('#folder-note').hidden = !boxes.some(box => box.dataset.folder === '1');
  deletion.querySelector('#delete-names').replaceChildren(...names.map(name => {
    const li = document.createElement('li');
    li.textContent = name;
    return li;
  }));
  deletion.showModal();
});
for (const button of document.querySelectorAll('.rename-action')) {
  button.addEventListener('click', () => {
    const input = renaming.querySelector('[name=to]');
    input.value = renaming.querySelector('[name=name]').value = button.dataset.name;
    renaming.showModal();
    input.focus();
    input.select();
  });
}
for (const button of document.querySelectorAll('[data-close]')) {
  button.addEventListener('click', () => button.closest('dialog').close());
}
