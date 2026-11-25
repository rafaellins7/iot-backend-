import os
import sys

# Garante path para src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import database


def aplicar_migracao():
    sql_path = os.path.join(os.path.dirname(__file__), "migracao_parecer_geracao.sql")
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    print("[MIGRAÇÃO] Conectando ao banco de dados...")
    with database.conectar() as conn:
        with conn.cursor() as cur:
            print("[MIGRAÇÃO] Executando migração em parecer_agronomico...")
            cur.execute(sql)
            conn.commit()

        # Validação pós-execução
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'parecer_agronomico' 
                  AND column_name IN ('em_geracao', 'erro_geracao');
            """)
            colunas = cur.fetchall()
            print("[MIGRAÇÃO] Colunas confirmadas:", colunas)

    print("[MIGRAÇÃO] Concluída com sucesso!")


if __name__ == "__main__":
    aplicar_migracao()
