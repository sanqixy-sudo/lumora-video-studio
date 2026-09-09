import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


class JobAssetsTemplateTests(unittest.TestCase):
    def render(self, files, output_file=None):
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "app/templates"), autoescape=True)
        return env.get_template("workbench/job_assets.html").render(files=files, output_file=output_file)

    def test_images_keep_order_and_original_links(self):
        files = [dict(id=i, file_type="reference_image_url", file_path=f"https://example.test/{i}.png?token=a&b=c", file_name="image", width=720, height=1280) for i in range(1, 7)]
        html = self.render(files)
        self.assertEqual(html.count("data-reference-image>"), 6)
        self.assertLess(html.index("/1.png"), html.index("/6.png"))
        self.assertIn("?token=a&amp;b=c", html)
        self.assertIn('referrerpolicy="no-referrer"', html)

    def test_invalid_scheme_never_becomes_link_or_image(self):
        html = self.render([dict(file_type="reference_image_url", file_path="javascript:alert(1)", file_name="invalid")])
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data-reference-image", html)

    def test_historical_upload_uses_authorized_route(self):
        html = self.render([dict(id=7, file_type="reference_image", file_path="/private/uploads/secret.png", file_name="old.png")])
        self.assertIn('/app/files/7/stream', html)
        self.assertNotIn('/private/uploads', html)

    def test_missing_video_does_not_offer_broken_download(self):
        files = [dict(id=9, file_type="output_video", file_name="result.mp4")]
        self.assertNotIn('/app/files/9/download', self.render(files))
        self.assertIn('/app/files/9/download', self.render(files, dict(id=9)))
