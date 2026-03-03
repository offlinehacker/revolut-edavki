import datetime
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class SyntheticRevolutPipelineTest(unittest.TestCase):
    def test_synthetic_csv_generates_expected_xml(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "revolut_davki.py"
        fixture_csv = repo_root / "tests" / "fixtures" / "revolut_synthetic_2025.csv"

        with tempfile.TemporaryDirectory(prefix="revolut-davki-test-") as tmpdir:
            tmp_path = Path(tmpdir)

            (tmp_path / "input.csv").write_text(
                fixture_csv.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (tmp_path / "taxpayer.xml").write_text(
                "<taxpayer>\n"
                "   <taxNumber>12345678</taxNumber>\n"
                "   <taxpayerType>FO</taxpayerType>\n"
                "   <name>Test Person</name>\n"
                "   <address1>Test Street 1</address1>\n"
                "   <city>Ljubljana</city>\n"
                "   <postNumber>1000</postNumber>\n"
                "   <postName>Ljubljana</postName>\n"
                "   <email>test@example.com</email>\n"
                "   <telephoneNumber>01 123 45 67</telephoneNumber>\n"
                "   <residentCountry>SI</residentCountry>\n"
                "   <isResident>true</isResident>\n"
                "</taxpayer>\n",
                encoding="utf-8",
            )

            today = datetime.date.today()
            bsrate_filename = f"bsrate-{today.year}{today.month}{today.day}.xml"
            (tmp_path / bsrate_filename).write_text(
                "<tecajnice>\n"
                "  <day datum=\"2025-01-24\">\n"
                "    <rate oznaka=\"USD\">1.25</rate>\n"
                "  </day>\n"
                "</tecajnice>\n",
                encoding="utf-8",
            )

            cmd = [
                sys.executable,
                str(script_path),
                "--csv",
                "input.csv",
                "-y",
                "2025",
                "--ignore-foreign-tax",
            ]
            result = subprocess.run(
                cmd,
                cwd=tmp_path,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"Converter failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
            )

            kdvp_xml = tmp_path / "Doh-KDVP.xml"
            difi_xml = tmp_path / "D-IFI.xml"
            div_xml = tmp_path / "Doh-Div.xml"
            obr_xml = tmp_path / "Doh-Obr.xml"

            for xml_path in [kdvp_xml, difi_xml, div_xml, obr_xml]:
                self.assertTrue(xml_path.exists(), msg=f"Missing output file: {xml_path}")

            kdvp_ns = "{http://edavki.durs.si/Documents/Schemas/Doh_KDVP_9.xsd}"
            kdvp_root = ET.parse(kdvp_xml).getroot()
            security_count = kdvp_root.find(f".//{kdvp_ns}SecurityCount")
            self.assertIsNotNone(security_count)
            self.assertEqual(security_count.text, "1")
            kdvp_rows = kdvp_root.findall(f".//{kdvp_ns}Row")
            self.assertEqual(len(kdvp_rows), 2)
            last_f8 = kdvp_rows[-1].find(f"{kdvp_ns}F8")
            self.assertIsNotNone(last_f8)
            self.assertEqual(last_f8.text, "0.0000")

            difi_ns = "{http://edavki.durs.si/Documents/Schemas/D_IFI_4.xsd}"
            difi_root = ET.parse(difi_xml).getroot()
            self.assertEqual(len(difi_root.findall(f".//{difi_ns}TItem")), 0)

            div_ns = "{http://edavki.durs.si/Documents/Schemas/Doh_Div_3.xsd}"
            div_root = ET.parse(div_xml).getroot()
            dividends = div_root.findall(f".//{div_ns}Dividend")
            self.assertEqual(len(dividends), 1)
            self.assertEqual(dividends[0].find(f"{div_ns}Value").text, "0.18")
            self.assertEqual(dividends[0].find(f"{div_ns}ForeignTax").text, "0.00")

            obr_ns = "{http://edavki.durs.si/Documents/Schemas/Doh_Obr_2.xsd}"
            obr_root = ET.parse(obr_xml).getroot()
            interests = obr_root.findall(f".//{obr_ns}Interest")
            self.assertEqual(len(interests), 1)
            self.assertEqual(interests[0].find(f"{obr_ns}Type").text, "7")
            self.assertEqual(interests[0].find(f"{obr_ns}Value").text, "0.70")
            self.assertEqual(interests[0].find(f"{obr_ns}ForeignTax").text, "0.00")
            self.assertEqual(
                interests[0].find(f"{obr_ns}IdentificationNumber").text,
                "305799582",
            )


if __name__ == "__main__":
    unittest.main()
