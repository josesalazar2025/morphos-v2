// @vitest-environment jsdom
// Prueba la ruta de inyección compartida (form-inject.ts) que usa el importador de
// analizadores: dado un ResultadoMapeado ya con claves canónicas, rellena los inputs por
// `name`, respeta los <select> semicuantitativos y dispara evaluar una sola vez.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { aplicarValoresAFormulario, aplicarPacienteAFormulario } from '../src/form-inject.js';

function montarFormulario(): void {
  document.body.innerHTML = `
    <input name="gluc" type="number">
    <input name="creat" type="number">
    <select name="uri-prot">
      <option value=""></option>
      <option value="+"></option>
      <option value="+++"></option>
    </select>
    <select id="pt-especie"><option value=""></option><option value="Canino"></option><option value="Felino"></option></select>
    <input id="pt-raza" type="text">
    <input id="pt-edad" type="number">
    <select id="pt-edad-unidad"><option value="anyos"></option><option value="meses"></option></select>
    <select id="pt-sexo"><option value=""></option><option value="Macho"></option><option value="Hembra"></option></select>
  `;
}

describe('aplicarValoresAFormulario', () => {
  beforeEach(montarFormulario);

  it('inyecta valores numéricos por name y llama evaluar una vez', () => {
    const evaluar = vi.fn();
    const n = aplicarValoresAFormulario({ gluc: 90, creat: 1.2 }, evaluar);
    expect(n).toBe(2);
    expect((document.querySelector('[name="gluc"]') as HTMLInputElement).value).toBe('90');
    expect((document.querySelector('[name="creat"]') as HTMLInputElement).value).toBe('1.2');
    expect(evaluar).toHaveBeenCalledTimes(1);
  });

  it('inyecta semicuantitativos sólo si la opción existe', () => {
    const evaluar = vi.fn();
    expect(aplicarValoresAFormulario({ 'uri-prot': '+++' }, evaluar)).toBe(1);
    expect((document.querySelector('[name="uri-prot"]') as HTMLSelectElement).value).toBe('+++');
    // Un valor de opción inexistente no se aplica.
    expect(aplicarValoresAFormulario({ 'uri-prot': '++++' }, evaluar)).toBe(0);
  });

  it('ignora claves sin campo y no llama evaluar si nada se rellenó', () => {
    const evaluar = vi.fn();
    expect(aplicarValoresAFormulario({ inexistente: 5 }, evaluar)).toBe(0);
    expect(evaluar).not.toHaveBeenCalled();
  });

  it('resalta los campos rellenados cuando se pide', () => {
    aplicarValoresAFormulario({ gluc: 90 }, () => {}, { resaltar: true });
    expect((document.querySelector('[name="gluc"]') as HTMLElement).classList.contains('campo-importado')).toBe(true);
  });
});

describe('aplicarPacienteAFormulario', () => {
  beforeEach(montarFormulario);

  it('rellena especie/raza/sexo/edad', () => {
    const n = aplicarPacienteAFormulario({ especie: 'Canino', raza: 'Labrador', sexo: 'Macho', edad: 3, edadUnidad: 'anyos' });
    expect(n).toBe(5);
    expect((document.getElementById('pt-especie') as HTMLSelectElement).value).toBe('Canino');
    expect((document.getElementById('pt-raza') as HTMLInputElement).value).toBe('Labrador');
    expect((document.getElementById('pt-sexo') as HTMLSelectElement).value).toBe('Macho');
    expect((document.getElementById('pt-edad') as HTMLInputElement).value).toBe('3');
  });
});
