// dashboard/static/js/reactionroles.js
(function () {
  function parseInitialData() {
    try {
      const scripts = document.getElementsByTagName('script');
      for (let i = 0; i < scripts.length; i++) {
        const t = scripts[i].textContent.trim();
        if (!t) continue;
        if (t.startsWith('{') && (t.includes('reaction_messages') || t.includes('preview') || t.includes('message'))) {
          return JSON.parse(t);
        }
      }
    } catch (e) {
      console.error('RR: failed to parse initial data', e);
    }
    return {};
  }

  function currentGuildId() {
    // Try to extract guild id from hash like #/dashboard/<guild_id>/...
    try {
      const hash = window.location.hash || '';
      const parts = hash.split('/');
      const idx = parts.indexOf('dashboard');
      if (idx !== -1 && parts.length > idx + 1) {
        const gid = parts[idx + 1];
        if (/^\d+$/.test(gid)) return gid;
      }
    } catch (e) {}
    // Fallback: try initial data (some integrations inject guild)
    const init = parseInitialData();
    if (init && init.guild && init.guild.id) return String(init.guild.id);
    if (init && init.reaction_messages && init.reaction_messages.length) {
      // no guild in data, but try to infer from first item channel id -> not reliable
    }
    return null;
  }

  function buildGuildLink(path) {
    const gid = currentGuildId();
    if (gid) {
      return `#/dashboard/${gid}/third-party/reaction_roles/${path}`;
    }
    return `#/third-party/reaction_roles/${path}`;
  }

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
      div.innerHTML = `<div><strong>Message ${it.message_id}</strong> in channel ${it.channel_id}</div>
                       <div>${(it.content||'')}</div>`;
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
      actions.innerHTML = `<a class="rr-button" href="${buildGuildLink('preview?message_id=' + it.message_id)}">Preview</a>
                           <a class="rr-button" href="${buildGuildLink('edit?message_id=' + it.message_id)}">Edit</a>`;
      div.appendChild(actions);
      container.appendChild(div);
    });
  }

  function postFormToParent(payload) {
    // include guild id so dashboard forwards it
    const gid = currentGuildId();
    if (gid) payload.guild_id = gid;
    if (window.parent && window.parent.postMessage) {
      window.parent.postMessage({ type: 'third_party_form_submit', payload: payload }, '*');
    } else {
      console.warn('RR: parent postMessage not available; copy payload manually', payload);
    }
  }

  function handleCreate() {
    const form = document.getElementById('rr-create-form');
    if (!form) return;
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      const payload = {
        channel_id: document.getElementById('channel_id').value.trim(),
        content: document.getElementById('content').value.trim(),
        mappings: document.getElementById('mappings').value.trim()
      };
      postFormToParent(payload);
      document.getElementById('rr-create-result').textContent = 'Submitted.';
    });
  }

  function handleEdit(initial) {
    const form = document.getElementById('rr-edit-form');
    if (!form) return;
    const contentEl = document.getElementById('content');
    const mappingsEl = document.getElementById('mappings');
    if (initial && initial.message) {
      contentEl.value = initial.message.content || '';
      const arr = initial.message.mapping ? Object.entries(initial.message.mapping).map(([e,r])=>({emoji:e,role_id:r})) : [];
      mappingsEl.value = JSON.stringify(arr, null, 2);
    }
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      const payload = {
        content: contentEl.value.trim(),
        mappings: mappingsEl.value.trim(),
        message_id: initial.message_id
      };
      postFormToParent(payload);
      document.getElementById('rr-edit-result').textContent = 'Submitted.';
    });
  }

  function renderPreview(initial) {
    const container = document.getElementById('rr-preview');
    if (!container) return;
    container.innerHTML = '';
    const preview = initial.preview || {};
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

  document.addEventListener('DOMContentLoaded', function () {
    const data = parseInitialData();
    if (document.getElementById('rr-list')) renderList(data);
    if (document.getElementById('rr-create-form')) handleCreate();
    if (document.getElementById('rr-edit-form')) handleEdit(data);
    if (document.getElementById('rr-preview')) renderPreview(data);
  });
})();
