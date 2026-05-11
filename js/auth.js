let estadoAuth = null;
let accionPendiente = null;

// Verificación de sesión 

export async function verificarAuth() {
    if (estadoAuth !== null) return estadoAuth;

    try {
        const resp = await fetch('api/auth.php');
        const datos = await resp.json();
        estadoAuth = datos.autenticado;
        if (estadoAuth) actualizarBtnUsuario(datos.nombre);
    } catch {
        estadoAuth = false;
    }
    return estadoAuth;
}

// Modal

const modal = document.getElementById('modal-auth');
const overlay = document.getElementById('modal-auth-overlay');
const btnCerrar = document.getElementById('modal-auth-cerrar');
const tabLogin = document.getElementById('auth-tab-login');
const tabRegistro = document.getElementById('auth-tab-registro');
const panelLogin = document.getElementById('auth-panel-login');
const panelRegistro = document.getElementById('auth-panel-registro');
const formLogin = document.getElementById('form-login');
const formRegistro = document.getElementById('form-registro');
const errorLogin = document.getElementById('auth-error-login');
const errorRegistro = document.getElementById('auth-error-registro');

function abrirModal() {
    modal.hidden = false;
    requestAnimationFrame(() => {
        modal.classList.add('visible');
        overlay.classList.add('activo');
    });
    formLogin.reset();
    formRegistro.reset();
    [formLogin, formRegistro].forEach(f =>
        f.querySelectorAll('input').forEach(limpiarCampo)
    );
    errorLogin.textContent = '';
    errorRegistro.textContent = '';
    activarTab('login');
}

function cerrarModal() {
    modal.classList.remove('visible');
    overlay.classList.remove('activo');
    modal.addEventListener('transitionend', () => { modal.hidden = true; }, { once: true });
    accionPendiente = null;
}

function activarTab(cual) {
    const esLogin = cual === 'login';
    tabLogin.classList.toggle('activo', esLogin);
    tabRegistro.classList.toggle('activo', !esLogin);
    panelLogin.hidden = !esLogin;
    panelRegistro.hidden = esLogin;
}

export function abrirModalAuth(callbackExito) {
    accionPendiente = callbackExito ?? null;
    abrirModal();
}

// Botón de usuario en header 

const btnUsuario = document.getElementById('btn-usuario');

const SVG_LOGIN  = `<svg xmlns="http://www.w3.org/2000/svg" height="20px" viewBox="0 -960 960 960" width="20px" fill="currentColor" aria-hidden="true"><path d="M480-120v-80h280v-560H480v-80h280q33 0 56.5 23.5T840-760v560q0 33-23.5 56.5T760-120H480Zm-80-160-55-58 102-102H120v-80h327L345-622l55-58 200 200-200 200Z"/></svg>`;
const SVG_LOGOUT = `<svg xmlns="http://www.w3.org/2000/svg" height="20px" viewBox="0 -960 960 960" width="20px" fill="currentColor" aria-hidden="true"><path d="M200-120q-33 0-56.5-23.5T120-200v-560q0-33 23.5-56.5T200-840h280v80H200v560h280v80H200Zm440-160-55-58 102-102H360v-80h327L585-622l55-58 200 200-200 200Z"/></svg>`;

function actualizarBtnUsuario(nombre) {
    if (!btnUsuario) return;
    btnUsuario.innerHTML = SVG_LOGOUT;
    btnUsuario.append(' ', nombre ?? 'Usuario');
    btnUsuario.dataset.tooltip = 'Cerrar sesión';
}

function resetearBtnUsuario() {
    if (!btnUsuario) return;
    btnUsuario.innerHTML = `${SVG_LOGIN} Login`;
    btnUsuario.dataset.tooltip = 'Iniciar sesión';
}

// Validación en tiempo real 

function esEmailValido(v) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());
}

function marcarCampo(input, valido) {
    input.classList.toggle('campo-valido', valido);
    input.classList.toggle('campo-invalido', !valido);
}

function limpiarCampo(input) {
    input.classList.remove('campo-valido', 'campo-invalido');
}

function activarValidacionCampo(input, reglaDeFalso) {
    let tocado = false;
    input.addEventListener('blur', () => { tocado = true; marcarCampo(input, !reglaDeFalso()); });
    input.addEventListener('input', () => { if (tocado) marcarCampo(input, !reglaDeFalso()); });
}

function inicializarValidacionLogin() {
    const email = formLogin.querySelector('[name="email"]');
    const password = formLogin.querySelector('[name="password"]');
    activarValidacionCampo(email, () => !esEmailValido(email.value));
    activarValidacionCampo(password, () => password.value.length < 1);
}

function inicializarValidacionRegistro() {
    const nombre = formRegistro.querySelector('[name="nombre"]');
    const apellido = formRegistro.querySelector('[name="apellido"]');
    const email = formRegistro.querySelector('[name="email"]');
    const password = formRegistro.querySelector('[name="password"]');
    const password2 = formRegistro.querySelector('[name="password2"]');

    activarValidacionCampo(nombre, () => nombre.value.trim().length < 1);
    activarValidacionCampo(apellido, () => apellido.value.trim().length < 1);
    activarValidacionCampo(email, () => !esEmailValido(email.value));
    activarValidacionCampo(password, () => password.value.length < 6);

    // password2 depende del valor de password, se re-evalúa en ambos
    let tocadoP2 = false;
    const validarP2 = () => password.value === password2.value && password2.value.length > 0;
    password2.addEventListener('blur', () => { tocadoP2 = true; marcarCampo(password2, validarP2()); });
    password2.addEventListener('input', () => { if (tocadoP2) marcarCampo(password2, validarP2()); });
    password.addEventListener('input', () => { if (tocadoP2) marcarCampo(password2, validarP2()); });
}

inicializarValidacionLogin();
inicializarValidacionRegistro();

// Manejo de formularios

async function enviarFormAuth(accion, campos) {
    try {
        const resp = await fetch('api/auth.php', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ accion, ...campos }),
        });
        return await resp.json();
    } catch {
        return { error: 'Error de conexión. Verifica tu red.' };
    }
}

formLogin.addEventListener('submit', async e => {
    e.preventDefault();
    errorLogin.textContent = '';
    const btn = formLogin.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = 'Ingresando…';

    const datos = await enviarFormAuth('login', {
        email: formLogin.querySelector('[name="email"]').value,
        password: formLogin.querySelector('[name="password"]').value,
    });

    btn.disabled = false;
    btn.textContent = 'Ingresar';

    if (datos.error) { errorLogin.textContent = datos.error; return; }

    estadoAuth = true;
    actualizarBtnUsuario(datos.nombre);
    cerrarModal();
    accionPendiente?.();
    accionPendiente = null;
});

formRegistro.addEventListener('submit', async e => {
    e.preventDefault();
    errorRegistro.textContent = '';
    const btn = formRegistro.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = 'Registrando…';

    const password = formRegistro.querySelector('[name="password"]').value;
    const password2 = formRegistro.querySelector('[name="password2"]').value;

    if (!formRegistro.querySelector('[name="aviso-legal"]').checked) {
        errorRegistro.textContent = 'Debes aceptar el aviso antes de crear una cuenta.';
        btn.disabled = false;
        btn.textContent = 'Crear cuenta';
        return;
    }

    if (password !== password2) {
        errorRegistro.textContent = 'Las contraseñas no coinciden.';
        btn.disabled = false;
        btn.textContent = 'Crear cuenta';
        return;
    }

    const datos = await enviarFormAuth('registro', {
        nombre: formRegistro.querySelector('[name="nombre"]').value,
        apellido: formRegistro.querySelector('[name="apellido"]').value,
        email: formRegistro.querySelector('[name="email"]').value,
        password,
    });

    btn.disabled = false;
    btn.textContent = 'Crear cuenta';

    if (datos.error) { errorRegistro.textContent = datos.error; return; }

    estadoAuth = true;
    actualizarBtnUsuario(datos.nombre);
    cerrarModal();
    accionPendiente?.();
    accionPendiente = null;
});

// Eventos de UI

tabLogin.addEventListener('click', () => activarTab('login'));
tabRegistro.addEventListener('click', () => activarTab('registro'));
btnCerrar.addEventListener('click', cerrarModal);
overlay.addEventListener('click', cerrarModal);
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) cerrarModal(); });

btnUsuario?.addEventListener('click', async () => {
    const autenticado = await verificarAuth();
    if (!autenticado) {
        abrirModal();
    } else {
        await fetch('api/auth.php', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ accion: 'logout' }),
        });
        estadoAuth = false;
        resetearBtnUsuario();
    }
});

verificarAuth();
