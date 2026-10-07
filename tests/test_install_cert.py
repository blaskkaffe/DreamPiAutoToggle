"""The self-signed certificate that install.sh makes: its openssl config must not hold a $VARIABLE (openssl expands it and fails with
'variable has no value', which showed as 'Could not create an HTTPS certificate')."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CertTests(unittest.TestCase):
    def test_the_config_install_sh_writes_gives_a_certificate(self):
        text = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
        line = [l for l in text.splitlines() if l.strip().startswith("printf '[req]")][0]
        d = tempfile.mkdtemp()
        try:
            script = 'HOST=testhost\nSAN="DNS:testhost.local,IP:127.0.0.1"\nCNF=%s/c.cnf\n%s\n' % (d, line.replace('"$CNF"', '"$CNF"'))
            subprocess.check_call(["sh", "-c", script])
            conf = open(os.path.join(d, "c.cnf")).read()
            self.assertIsNone(re.search(r"\$\w", conf), "a $variable in the openssl config")
            self.assertIn("CN=testhost.local", conf)
            if shutil.which("openssl"):
                r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "2", "-keyout", d + "/k", "-out", d + "/c",
                                    "-config", d + "/c.cnf"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertEqual(r.returncode, 0, r.stdout.decode())
                self.assertTrue(os.path.getsize(d + "/c") > 0)
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
