# GraphRAG Brand Fonts

This directory must contain the following 8 font files sourced from Google Fonts
(Open Font License) before the application will render correctly:

| File | Family | Weight |
|------|--------|--------|
| `CormorantGaramond-Regular.ttf` | Cormorant Garamond | Regular |
| `CormorantGaramond-Medium.ttf` | Cormorant Garamond | Medium |
| `CormorantGaramond-SemiBold.ttf` | Cormorant Garamond | SemiBold |
| `DMSans-Regular.ttf` | DM Sans | Regular |
| `DMSans-Medium.ttf` | DM Sans | Medium |
| `DMSans-Bold.ttf` | DM Sans | Bold |
| `DMMono-Regular.ttf` | DM Mono | Regular |
| `DMMono-Medium.ttf` | DM Mono | Medium |

## Download Instructions

1. Visit https://fonts.google.com/
2. Search for each family name
3. Download the `.ttf` files for the weights listed above
4. Place them in this directory (`gui/assets/fonts/`)

If any font file is missing, `FontLoader` will fall back to system defaults
(Georgia, Segoe UI, Consolas) without raising an exception.
