// Autenticación (modal login/registro + estado de sesión).
// Puerto TS de js/auth.js, apuntando a los nuevos endpoints FastAPI /api/auth/*.

import { elId, elIdOpt } from './dom.js';
import { manejadorAsync, sinEsperar } from './async.js';

let estadoAuth: boolean | null = null;
let accionPendiente: (() => void) | null = null;

// Extrae un mensaje de error legible de una respuesta FastAPI ({detail: str | [...]}).
function mensajeError(datos: unknown, fallback: string): string {
  if (datos && typeof datos === 'object' && 'detail' in datos) {
    const d = (datos as { detail: unknown }).detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d.length && typeof d[0]?.msg === 'string') return d[0].msg;
  }
  if (datos && typeof datos === 'object' && 'error' in datos) {
    return String((datos as { error: unknown }).error);
  }
  return fallback;
}

// Verificación de sesión

export async function verificarAuth(): Promise<boolean> {
  if (estadoAuth !== null) return estadoAuth;

  try {
    const resp = await fetch('/api/auth', { credentials: 'same-origin' });
    const datos = await resp.json();
    estadoAuth = Boolean(datos.autenticado);
    if (estadoAuth) actualizarBtnUsuario(datos.nombre);
  } catch {
    estadoAuth = false;
  }
  return estadoAuth;
}

// Modal

const modal = elId('modal-auth');
const overlay = elId('modal-auth-overlay');
const btnCerrar = elId('modal-auth-cerrar');
const tabLogin = elId('auth-tab-login');
const tabRegistro = elId('auth-tab-registro');
const panelLogin = elId('auth-panel-login');
const panelRegistro = elId('auth-panel-registro');
const formLogin = elId<HTMLFormElement>('form-login');
const formRegistro = elId<HTMLFormElement>('form-registro');
const errorLogin = elId('auth-error-login');
const errorRegistro = elId('auth-error-registro');

function abrirModal(): void {
  modal.hidden = false;
  requestAnimationFrame(() => {
    modal.classList.add('visible');
    overlay.classList.add('activo');
  });
  formLogin.reset();
  formRegistro.reset();
  [formLogin, formRegistro].forEach((f) =>
    f.querySelectorAll<HTMLInputElement>('input').forEach(limpiarCampo),
  );
  errorLogin.textContent = '';
  errorRegistro.textContent = '';
  activarTab('login');
}

function cerrarModal(): void {
  modal.classList.remove('visible');
  overlay.classList.remove('activo');
  modal.addEventListener('transitionend', () => { modal.hidden = true; }, { once: true });
  accionPendiente = null;
}

function activarTab(cual: string): void {
  const esLogin = cual === 'login';
  tabLogin.classList.toggle('activo', esLogin);
  tabRegistro.classList.toggle('activo', !esLogin);
  panelLogin.hidden = !esLogin;
  panelRegistro.hidden = esLogin;
}

export function abrirModalAuth(callbackExito?: () => void): void {
  accionPendiente = callbackExito ?? null;
  abrirModal();
}

// Botón de usuario en header

const btnUsuario = elIdOpt('btn-usuario');

const SVG_LOGIN = `<svg xmlns="http://www.w3.org/2000/svg" height="20px" viewBox="0 -960 960 960" width="20px" fill="currentColor" aria-hidden="true"><path d="M480-120v-80h280v-560H480v-80h280q33 0 56.5 23.5T840-760v560q0 33-23.5 56.5T760-120H480Zm-80-160-55-58 102-102H120v-80h327L345-622l55-58 200 200-200 200Z"/></svg>`;
const SVG_LOGOUT = `<svg xmlns="http://www.w3.org/2000/svg" height="20px" viewBox="0 -960 960 960" width="20px" fill="currentColor" aria-hidden="true"><path d="M200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h280v80H200v560h280v80H200Zm440-160-55-58 102-102H360v-80h327L585-622l55-58 200 200-200 200Z"/></svg>`;

function actualizarBtnUsuario(nombre?: string): void {
  if (!btnUsuario) return;
  btnUsuario.innerHTML = SVG_LOGOUT;
  btnUsuario.append(' ', nombre ?? 'Usuario');
  btnUsuario.dataset.tooltip = 'Cerrar sesión';
}

function resetearBtnUsuario(): void {
  if (!btnUsuario) return;
  btnUsuario.innerHTML = `${SVG_LOGIN} Login`;
  btnUsuario.dataset.tooltip = 'Iniciar sesión';
}

// Validación en tiempo real

function esEmailValido(v: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());
}

function marcarCampo(input: HTMLInputElement, valido: boolean): void {
  input.classList.toggle('campo-valido', valido);
  input.classList.toggle('campo-invalido', !valido);
}

function limpiarCampo(input: HTMLInputElement): void {
  input.classList.remove('campo-valido', 'campo-invalido');
}

function activarValidacionCampo(input: HTMLInputElement, reglaDeFalso: () => boolean): void {
  let tocado = false;
  input.addEventListener('blur', () => { tocado = true; marcarCampo(input, !reglaDeFalso()); });
  input.addEventListener('input', () => { if (tocado) marcarCampo(input, !reglaDeFalso()); });
}

function q(form: HTMLFormElement, name: string): HTMLInputElement {
  return form.querySelector<HTMLInputElement>(`[name="${name}"]`)!;
}

function inicializarValidacionLogin(): void {
  const email = q(formLogin, 'email');
  const password = q(formLogin, 'password');
  activarValidacionCampo(email, () => !esEmailValido(email.value));
  activarValidacionCampo(password, () => password.value.length < 1);
}

function inicializarValidacionRegistro(): void {
  const nombre = q(formRegistro, 'nombre');
  const apellido = q(formRegistro, 'apellido');
  const email = q(formRegistro, 'email');
  const password = q(formRegistro, 'password');
  const password2 = q(formRegistro, 'password2');

  activarValidacionCampo(nombre, () => nombre.value.trim().length < 1);
  activarValidacionCampo(apellido, () => apellido.value.trim().length < 1);
  activarValidacionCampo(email, () => !esEmailValido(email.value));
  activarValidacionCampo(password, () => password.value.length < 8);

  let tocadoP2 = false;
  const validarP2 = () => password.value === password2.value && password2.value.length > 0;
  password2.addEventListener('blur', () => { tocadoP2 = true; marcarCampo(password2, validarP2()); });
  password2.addEventListener('input', () => { if (tocadoP2) marcarCampo(password2, validarP2()); });
  password.addEventListener('input', () => { if (tocadoP2) marcarCampo(password2, validarP2()); });
}

inicializarValidacionLogin();
inicializarValidacionRegistro();

// Manejo de formularios

async function enviarAuth(ruta: string, campos: Record<string, string>): Promise<{ ok?: boolean; nombre?: string; _error?: string }> {
  try {
    const resp = await fetch(`/api/auth/${ruta}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(campos),
    });
    const datos = await resp.json().catch(() => ({}));
    if (!resp.ok) return { _error: mensajeError(datos, `Error ${resp.status}`) };
    return datos;
  } catch {
    return { _error: 'Error de conexión. Verifica tu red.' };
  }
}

formLogin.addEventListener('submit', manejadorAsync('Inicio de sesión', async (e: Event) => {
  e.preventDefault();
  errorLogin.textContent = '';
  const btn = formLogin.querySelector<HTMLButtonElement>('button[type="submit"]')!;
  btn.disabled = true;
  btn.textContent = 'Ingresando…';

  try {
    const datos = await enviarAuth('login', {
      email: q(formLogin, 'email').value,
      password: q(formLogin, 'password').value,
    });

    if (datos._error) { errorLogin.textContent = datos._error; return; }

    estadoAuth = true;
    actualizarBtnUsuario(datos.nombre);
    cerrarModal();
    accionPendiente?.();
    accionPendiente = null;
  } finally {
    // En finally: si algo lanza, el botón no puede quedarse deshabilitado para siempre.
    btn.disabled = false;
    btn.textContent = 'Ingresar';
  }
}));

formRegistro.addEventListener('submit', manejadorAsync('Registro', async (e: Event) => {
  e.preventDefault();
  errorRegistro.textContent = '';
  const btn = formRegistro.querySelector<HTMLButtonElement>('button[type="submit"]')!;
  btn.disabled = true;
  btn.textContent = 'Registrando…';

  try {
    const password = q(formRegistro, 'password').value;
    const password2 = q(formRegistro, 'password2').value;

    const avisoLegal = formRegistro.querySelector<HTMLInputElement>('[name="aviso-legal"]');
    if (avisoLegal && !avisoLegal.checked) {
      errorRegistro.textContent = 'Debes aceptar el aviso antes de crear una cuenta.';
      return;
    }

    if (password !== password2) {
      errorRegistro.textContent = 'Las contraseñas no coinciden.';
      return;
    }

    const datos = await enviarAuth('registro', {
      nombre: q(formRegistro, 'nombre').value,
      apellido: q(formRegistro, 'apellido').value,
      email: q(formRegistro, 'email').value,
      password,
    });

    if (datos._error) { errorRegistro.textContent = datos._error; return; }

    estadoAuth = true;
    actualizarBtnUsuario(datos.nombre);
    cerrarModal();
    accionPendiente?.();
    accionPendiente = null;
  } finally {
    // Un único punto de restauración del botón: antes se repetía en cada rama de salida y no
    // cubría el caso de excepción.
    btn.disabled = false;
    btn.textContent = 'Crear cuenta';
  }
}));

// Eventos de UI

tabLogin.addEventListener('click', () => activarTab('login'));
tabRegistro.addEventListener('click', () => activarTab('registro'));
btnCerrar.addEventListener('click', cerrarModal);
overlay.addEventListener('click', cerrarModal);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !modal.hidden) cerrarModal(); });

btnUsuario?.addEventListener('click', manejadorAsync('Sesión', async () => {
  const autenticado = await verificarAuth();
  if (!autenticado) {
    abrirModal();
  } else {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    estadoAuth = false;
    resetearBtnUsuario();
  }
}));

// Comprobación de sesión al cargar: no hay nada que esperar, pero un fallo debe verse.
sinEsperar('Comprobación de sesión', verificarAuth());
