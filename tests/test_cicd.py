import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CicdTest(unittest.TestCase):
    def test_validacao_estatica_da_esteira(self):
        resultado = subprocess.run(
            [sys.executable, "scripts/validate_cicd.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, resultado.returncode, resultado.stdout + resultado.stderr)
        self.assertIn('"status": "APROVADO"', resultado.stdout)

    def test_ci_roda_em_pr_e_nao_inicia_banco(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", ci)
        self.assertIn("python -m unittest discover -s tests -v", ci)
        self.assertIn("docker compose --profile pipeline config --quiet", ci)
        self.assertNotIn("docker compose up", ci)
        self.assertNotIn("docker compose run", ci)

    def test_cd_requer_runner_local_pr_e_nao_migra(self):
        cd = (ROOT / ".github/workflows/cd.yml").read_text(encoding="utf-8")
        deploy = (ROOT / "scripts/deploy-local.ps1").read_text(encoding="utf-8")
        self.assertIn("runs-on: [self-hosted, Windows, pdoh-cx-local]", cd)
        self.assertIn("Exigir PR com CI aprovado", cd)
        self.assertIn("PDOH_CX_ALLOWED_REPOSITORY", cd)
        self.assertIn("--no-deps", deploy)
        self.assertIn("backend backend", deploy)
        for comando in (
            "docker compose down",
            "docker volume",
            "docker system",
            "--profile pipeline run",
            "--profile pipeline up",
        ):
            self.assertNotIn(comando, deploy.lower())

    def test_segredos_e_evidencias_estao_ignorados(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn(".env.*", gitignore)
        self.assertIn("!.env.example", gitignore)
        self.assertIn("artifacts/", gitignore)
        self.assertIn(".env.*", dockerignore)
        self.assertIn("artifacts/", dockerignore)


if __name__ == "__main__":
    unittest.main()
