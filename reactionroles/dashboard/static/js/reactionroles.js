// reactionroles.js
(function () {
  // Utility: parse initial data injected by integration
  function initialData() {
    try {
      // The integration replaces /*__INITIAL_DATA__*/ with a JSON literal
      const scripts = document.getElementsByTagName('script');
      for (let i = 0; i < scripts.length; i++) {
        const t = scripts[i].textContent.trim();
        if (t && t.startsWith('{') && t.includes('reaction_messages') || t.includes('preview') || t.includes('message')) {
          return JSON.parse(t);
        }
      }
    } catch (e) {
      console.error('RR: failed to parse initial data', e);
    }
    return {};
  }

  // Render list page
  function renderList(data) {
    const container = document.getElementById('rr-list');
    if (!container) return;
    container.innerHTML = '';
    const items = (data.reaction_messages || []);
    if (!items.length) {
      container.innerHTML = '<p>No reaction role messages configured.</p>';
      return;
    }
    items.forEach(it => {
      const div = document.createElement('div');
      div.className = 'rr-list-item';
      const header = document.createElement('div');
      header.innerHTML = `<strong>Message ${it.message_id}</strong> in channel ${it.channel_id}`;
      div.appendChild(header);
      const content = document.createElement('div');
      content.textContent = it.content || '';
      div.appendChild(content);
      const mappings = document.createElement('div');
      (it.mappings || []).forEach(m => {
        const span = document.createElement('span');
        span.className = 'rr-mapping';
        span.textContent = `${m.emoji} → ${m.role_id}`;
        mappings.appendChild(span);
      });
      div.appendChild(mappings);
      const actions = document.createElement('div');
      actions.style.marginTop = '8px';
      actions.innerHTML = `<a class="rr-button" href="#/third-party/reaction_roles/preview?message_id=${it.message_id}">Preview</a> <a class="rr-button" href="#/third-party/reaction_roles/edit?message_id=${it.message_id}">Edit</a>`;
      div.appendChild(actions);
      container.appendChild(div);
    });
  }

  // Handle create form submission by calling dashboard RPC via form POST (dashboard will forward)
  function handleCreate() {
    const form = document.getElementById('rr-create-form');
    if (!form) return;
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      const channel_id = document.getElementById('channel_id').value.trim();
      const content = document.getElementById('content').value.trim();
      const mappings = document.getElementById('mappings').value.trim();
      const payload = {
        channel_id: channel_id,
        content: content,
        mappings: mappings
      };
      // The dashboard RPC will POST form_data to the integration; the dashboard UI handles this.
      // We simulate by calling the parent window if available, otherwise show JSON for manual copy.
      if (window.parent && window.parent.postMessage) {
        window.parent.postMessage({ type: 'third_party_form_submit', payload: payload }, '*');
      }
      const res = document.getElementById('rr-create-result');
      res.textContent = 'Submitted. If the dashboard supports form POST, the server will create the message.';
    });
  }

  // Handle edit form: prefill and submit
  function handleEdit(initial) {
    const form = document.getElementById('rr-edit-form');
    if (!form) return;
    const contentEl = document.getElementById('content');
    const mappingsEl = document.getElementById('mappings');
    if (initial && initial.message) {
      contentEl.value = initial.message.content || '';
      mappingsEl.value = JSON.stringify((initial.message.mapping ? Object.entries(initial.message.mapping).map(([e,r]) => ({emoji:e, role_id:r})) : []), null, 2);
    }
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      const content = contentEl.value.trim();
      const mappings = mappingsEl.value.trim();
      const payload = {
        content: content,
        mappings: mappings,
        message_id: initial.message_id
      };
      if (window.parent && window.parent.postMessage) {
        window.parent.postMessage({ type: 'third_party_form_submit', payload: payload }, '*');
      }
      const res = document.getElementById('rr-edit-result');
      res.textContent = 'Submitted. If the dashboard supports form POST, the server will update the message.';
    });
  }

  // Render preview
  function renderPreview(initial) {
    const container = document.getElementById('rr-preview');
    if (!container) return;
    const preview = initial.preview || {};
    container.innerHTML = '';
    const content = document.createElement('div');
    content.textContent = preview.content || '';
    container.appendChild(content);
    const mappings = document.createElement('div');
    (preview.mappings || []).forEach(m => {
      const span = document.createElement('span');
      span.className = 'rr-mapping';
      span.textContent = `${m.emoji} → ${m.role_id}`;
      mappings.appendChild(span);
    });
    container.appendChild(mappings);
  }

  // Auto-run based on which elements exist
  document.addEventListener('DOMContentLoaded', function () {
    const data = initialData();
    if (document.getElementById('rr-list')) {
      renderList(data);
    }
    if (document.getElementById('rr-create-form')) {
      handleCreate();
    }
    if (document.getElementById('rr-edit-form')) {
      handleEdit(data);
    }
    if (document.getElementById('rr-preview')) {
      renderPreview(data);
    }
  });
})();
