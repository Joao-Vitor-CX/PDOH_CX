import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 3307
    user: str = "pdoh_cx_reader"
    password: str = field(default="", repr=False)
    token: str = field(default="", repr=False)
    # Conta de EDICAO de regras (opcional). Sem senha a API segue somente leitura.
    config_user: str = "pdoh_cx_config"
    config_password: str = field(default="", repr=False)
    origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")

    @classmethod
    def load(cls):
        values = {**dotenv_values(ROOT / ".env.api"), **os.environ}
        result = cls(
            host=values.get("PDOH_API_DB_HOST", "127.0.0.1"),
            port=int(values.get("PDOH_API_DB_PORT", "3307")),
            user=values.get("PDOH_API_DB_USER", "pdoh_cx_reader"),
            password=values.get("PDOH_API_DB_PASSWORD", ""),
            token=values.get("PDOH_API_TOKEN", ""),
            config_user=values.get("PDOH_API_CONFIG_DB_USER", "pdoh_cx_config"),
            config_password=values.get("PDOH_API_CONFIG_DB_PASSWORD", ""),
            origins=tuple(x.strip() for x in values.get("PDOH_API_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if x.strip()),
        )
        if result.host not in {"127.0.0.1", "localhost", "mysql"}:
            raise ValueError("A API desta fase admite somente MySQL local.")
        if not result.password or len(result.token) < 32:
            raise ValueError("Configure PDOH_API_DB_PASSWORD e PDOH_API_TOKEN (minimo 32 caracteres) em api/.env.api.")
        if "*" in result.origins:
            raise ValueError("Configure origens CORS explicitas.")
        return result

    def url(self):
        return URL.create("mysql+pymysql", username=self.user, password=self.password,
                          host=self.host, port=self.port, database="pdoh_controle",
                          query={"charset": "utf8mb4"})

    def config_url(self):
        return URL.create("mysql+pymysql", username=self.config_user, password=self.config_password,
                          host=self.host, port=self.port, database="pdoh_controle",
                          query={"charset": "utf8mb4"})
