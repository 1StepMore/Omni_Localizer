from ol_post.punctuation import normalize, normalize_to_chinese, normalize_to_english


class TestNormalizeMultiLang:
    def test_en_ja_punctuation(self):
        assert normalize("Hello, world.", "en", "ja") == "Hello\u3001 world\u3002"

    def test_en_fr_noop(self):
        """French uses ASCII punctuation — no change needed."""
        assert normalize("Hello, world.", "en", "fr") == "Hello, world."

    def test_en_de_noop(self):
        assert normalize("Hello, world.", "en", "de") == "Hello, world."

    def test_en_ru_noop(self):
        assert normalize("Hello, world.", "en", "ru") == "Hello, world."

    def test_en_ko_noop(self):
        assert normalize("Hello, world.", "en", "ko") == "Hello, world."

    def test_unknown_pair_noop(self):
        assert normalize("Hello, world.", "en", "ar") == "Hello, world."
        assert normalize("Hello, world.", "es", "pt") == "Hello, world."


class TestBackwardCompat:
    def test_normalize_to_chinese_wrapper(self):
        assert normalize_to_chinese("a, b, c.") == "a\uff0c b\uff0c c\u3002"

    def test_normalize_to_english_wrapper(self):
        assert normalize_to_english("a\uff0c b\uff0c c\u3002") == "a, b, c."
