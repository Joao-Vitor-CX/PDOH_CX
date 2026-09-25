"""Smoke MySQL com a conta restrita: toda escrita sintetica e revertida na transacao."""
from contextlib import contextmanager
from pathlib import Path
import sys
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api.app.config import Settings
from api.app.rule_admin import RuleWriter, RuleCreate, RuleEdit, criar_regra, atualizar_regra
from shared.operational_schedule import TABLE


def main():
    writer = RuleWriter(Settings.load())
    writer.initialize()
    if not writer.disponivel:
        raise RuntimeError('Conta de configuracao indisponivel.')
    try:
        with writer.engine.connect() as connection:
            transaction = connection.begin()
            class TransactionWriter:
                tables = writer.tables

                @contextmanager
                def begin(self):
                    yield connection
            try:
                rule_table = writer.tables['regra_configuracao']
                exists = connection.execute(select(rule_table.c.configuracao_id).where(
                    rule_table.c.marca == 'BRACELL', rule_table.c.operacao == 'EXCLUSIVA',
                    rule_table.c.codigo_interno == 'CHECKOUT_AUSENTE')).first()
                if exists:
                    raise RuntimeError('Validacao nao altera configuracao existente de checkout.')
                scope = dict(marca='BRACELL', operacao='EXCLUSIVA')
                audit = dict(usuario='validacao_local', motivo='Validacao transacional com rollback')
                schedule = dict(jornada=44, ativo=True, hora_entrada_padrao='08:00', hora_saida_padrao='19:00')
                code, _ = criar_regra(TransactionWriter(), **scope, criacao=RuleCreate(**audit,
                    nome_regra='Validacao temporaria de checkout', descricao='Validacao sem persistencia',
                    tipo_oportunidade='CHECKOUT_AUSENTE', papel_fonte='checkout', campo_logico='hora_saida',
                    operador='IS NULL', jornadas=[schedule], status='INATIVA'))
                atualizar_regra(TransactionWriter(), **scope, codigo=code,
                    edicao=RuleEdit(**audit, jornadas=[{**schedule, 'hora_saida_padrao': '18:00'}]))
                table = writer.tables[TABLE]
                row = connection.execute(select(table).where(table.c.marca == 'BRACELL', table.c.jornada == 44)).mappings().one()
                assert row['hora_saida_padrao'] == '18:00'
            finally:
                transaction.rollback()
        print('MYSQL_CONFIGURACAO_OK: INSERT, UPDATE e auditoria verificados; transacao revertida.')
    finally:
        writer.close()


if __name__ == '__main__':
    main()
