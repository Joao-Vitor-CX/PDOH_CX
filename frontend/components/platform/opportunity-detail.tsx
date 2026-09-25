import { Link } from 'react-router-dom';

/** Compatibility for archived pages; historical IDs are not operational cards. */
export function OpportunityDetail(_props: {
  id: string;
  historyPage: number;
  onHistoryPage: (page: number) => void;
  onClose?: () => void;
}) {
  return <p className="rounded-xl border bg-white p-5 text-sm">
    Esta consulta usava registros históricos individuais.{' '}
    <Link className="font-semibold text-blue-700" to="/oportunidades">Consultar problemas operacionais agrupados</Link>
  </p>;
}
