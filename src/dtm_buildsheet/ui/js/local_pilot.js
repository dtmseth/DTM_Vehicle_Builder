/* Injected only by the disposable headless launcher. */
(() => {
  const panel = document.createElement('details');
  panel.className = 'local-pilot-panel';
  const summary = document.createElement('summary');
  summary.textContent = 'Local prototype · Cloud off · Downloads';
  panel.appendChild(summary);
  const note = document.createElement('p');
  note.textContent = 'Synthetic data only. Sign-in, Estimates, shared publication and native folder actions are unavailable.';
  panel.appendChild(note);
  const refresh = document.createElement('button');
  refresh.textContent = 'Refresh downloads';
  panel.appendChild(refresh);
  const list = document.createElement('ul');
  panel.appendChild(list);
  async function load() {
    const result = await fetch('/api/pilot/artifacts').then(r => r.json());
    list.replaceChildren();
    for (const artifact of result.artifacts || []) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = artifact.url;
      link.textContent = artifact.name;
      link.download = artifact.name;
      item.appendChild(link);
      list.appendChild(item);
    }
    if (!list.children.length) list.textContent = 'Generate a build PDF to see downloads here.';
  }
  panel.addEventListener('toggle', () => { if (panel.open) load(); });
  refresh.addEventListener('click', load);
  document.body.prepend(panel);
})();
