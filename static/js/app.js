/* ============================================================
   Bolão Copa 2026 — app.js
   Utilitários globais: toast, helpers de API
   ============================================================ */

// ── TOAST ─────────────────────────────────────────────────
(function setupToast() {
  const container = document.createElement('div');
  container.id = 'toast-container';
  document.body.appendChild(container);
})();

/**
 * Exibe uma notificação toast.
 * @param {string} msg - Mensagem a exibir
 * @param {'success'|'error'|'info'} tipo - Tipo visual
 * @param {number} duracao - Milissegundos (padrão: 3000)
 */
function showToast(msg, tipo = 'info', duracao = 3000) {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast--${tipo}`;
  el.textContent = msg;
  container.appendChild(el);

  // Anima entrada
  requestAnimationFrame(() => {
    requestAnimationFrame(() => el.classList.add('toast--show'));
  });

  // Remove após duração
  setTimeout(() => {
    el.classList.remove('toast--show');
    setTimeout(() => el.remove(), 300);
  }, duracao);
}

// ── REQUISIÇÕES FETCH HELPERS ──────────────────────────────
async function apiPost(url, body) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  return { ok: resp.ok, status: resp.status, data };
}

// ── ABAS GENÉRICAS ─────────────────────────────────────────
/**
 * Troca de aba genérica. Usa atributo data-tab no botão
 * e id="tab-{nome}" no painel.
 */
function showTab(nome, btnEl) {
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.admin-tab, .tab-btn').forEach(el =>
    el.classList.remove('admin-tab--active', 'tab-btn--active')
  );
  const panel = document.getElementById(`tab-${nome}`);
  if (panel) panel.style.display = '';
  if (btnEl) {
    btnEl.classList.add('admin-tab--active');
    btnEl.classList.add('tab-btn--active');
  }
}

// ── FILTRO DE RANKING POR FASE ─────────────────────────────
function filtrarRanking(faseId) {
  // Placeholder — o ranking por fase pode ser expandido futuramente
  showToast(`Filtro por fase em breve`, 'info');
}

// ── COPIAR PARA CLIPBOARD ──────────────────────────────────
async function copiarTexto(texto) {
  try {
    await navigator.clipboard.writeText(texto);
    showToast('Copiado!', 'success');
  } catch {
    showToast('Não foi possível copiar automaticamente', 'error');
  }
}

// ── FORMATAÇÃO DE DATA ─────────────────────────────────────
function formatarData(isoString) {
  if (!isoString) return '—';
  const d = new Date(isoString);
  return d.toLocaleDateString('pt-BR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

// ── CONFIRMAÇÃO SIMPLES ────────────────────────────────────
function confirmar(msg) {
  return window.confirm(msg);
}

// ── SCROLL TO TOP ──────────────────────────────────────────
function scrollTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
