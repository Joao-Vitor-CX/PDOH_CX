/**
 * Identidade da operação atendida. Único ponto acoplado ao nome — componentes e
 * páginas leem daqui, nunca embutem a marca. Para atender outra operação, troca-se
 * este arquivo (ou passa-se a resolvê-lo pela API), sem tocar em componente algum.
 */
export const OPERACAO = {
  /** Marca enviada à API. Hoje há uma só operação; não existe seletor na interface. */
  marca: 'BRACELL',
  nome: 'Bracell',
  logo: '/bracell.png',
  titulo: 'Painel PDOH',
  descricao: 'Gestão da produtividade da operação',
} as const;
