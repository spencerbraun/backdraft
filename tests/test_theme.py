"""Themes: the allowlists, the validation, and the block they compile to.

Two things are load-bearing here. The first is that theming is **inert by
default** — `theme=None` must produce the bytes the renderer produced before
themes existed, which is why the override is a block after the stylesheet and
not an edit to it. The second is that a theme's values land inside a `<style>`
element, so every value is checked before it gets there: a theme may restyle the
artifact and may not end the element, change the layout, or reach the network.

`themes/default.toml` is pinned against the stylesheet's own `:root`, which
makes the bundled default the audit as well as the reference sample.
"""

from __future__ import annotations

import pytest

from backdraft.kernel.errors import BackdraftError
from backdraft.kernel.model import BindReport
from backdraft.render import html, theme
from backdraft.render.html.assets import STYLESHEET

from css_util import by_selector, root_variables

DEFAULT_HEADINGS = (
    f"{theme.HEADING_SELECTOR}{{font-family:var(--serif);text-transform:none;"
    "font-variant:normal;font-weight:600;letter-spacing:normal}"
)


def load(body: str) -> theme.Theme:
    return theme.loads(body, name="under-test")


# ---- the allowlist is the stylesheet ----------------------------------------


def test_the_allowlist_is_every_themeable_root_variable() -> None:
    """A variable added to `:root` and not here is a knob nobody can turn."""
    declared = set(root_variables(STYLESHEET)) - {"rail-w"}
    assert declared == {*theme.COLOR_VARS, *theme.FONT_VARS}


def test_layout_and_color_scheme_stay_outside_the_allowlist() -> None:
    """Themes are display, not layout, and the artifact never follows the
    reader's system theme."""
    assert "rail-w" not in (*theme.COLOR_VARS, *theme.FONT_VARS)
    assert by_selector(STYLESHEET)[":root"]["color-scheme"] == "light"


def test_an_image_sits_on_the_themed_surface_not_on_white() -> None:
    """`background:#fff` behind an image was white by coincidence, not by
    intent: it is the artifact's surface, so it tracks `paper` like every other
    surface. Nothing shows through an opaque WebP today — every stored image is
    RGB — so this is a dead constant made correct, not a visible fix."""
    sheet = by_selector(STYLESHEET)
    assert sheet[".plate img"]["background"] == "var(--paper)"
    assert sheet[".overlay > img"]["background"] == "var(--paper)"


def test_the_bundled_default_restates_the_stylesheet() -> None:
    default = theme.resolve("default")
    assert default is not None
    expected = {k: v for k, v in root_variables(STYLESHEET).items() if k != "rail-w"}
    assert default.variables == expected, "drifted from the stylesheet's :root"


def test_every_document_heading_level_is_styled() -> None:
    """The markdown renderer emits h1-h6. A level with no rule falls to the
    browser's default mid-document, which is the bug this pins shut."""
    sheet = by_selector(STYLESHEET)
    for level in range(1, 7):
        assert f".doc h{level}" in sheet, f"h{level} falls to the browser's default"


def test_a_themes_heading_treatment_reaches_every_level() -> None:
    """Small-caps section heads and a body-face subsection would read as a
    mistake, so the theme's one heading rule covers the whole scale."""
    styled = theme.resolve("press").css()
    for selector in (".masthead h1", *(f".doc h{n}" for n in range(2, 7))):
        assert selector in styled


def test_the_bundled_default_headings_are_the_stylesheets() -> None:
    """The default's heading block is a no-op restatement of the base rules."""
    sheet = by_selector(STYLESHEET)
    for selector in theme.HEADING_SELECTOR.split(","):
        if selector != ".masthead h1":
            assert sheet[selector]["font-family"] == "var(--serif)"
        assert sheet[selector]["font-weight"] == "600"
    assert theme.resolve("default").css().endswith(DEFAULT_HEADINGS)


def test_every_bundled_theme_loads() -> None:
    assert theme.bundled_names() == ("default", "press", "slate")
    for name in theme.bundled_names():
        assert theme.resolve(name).css()


# ---- inert by default -------------------------------------------------------


def test_no_theme_renders_exactly_what_it_always_did(
    demo_doc: str, demo: BindReport
) -> None:
    assert html.render(demo_doc, demo, theme=None) == html.render(demo_doc, demo)


def test_a_theme_adds_a_block_and_changes_nothing_else(
    demo_doc: str, demo: BindReport
) -> None:
    plain = html.render(demo_doc, demo)
    styled = html.render(demo_doc, demo, theme=theme.resolve("slate"))
    assert len(styled) == len(plain) + len(theme.resolve("slate").css()) + 1
    assert plain.replace("</style>", f"\n{theme.resolve('slate').css()}</style>") == styled


def test_the_default_theme_and_no_theme_style_the_same(
    demo_doc: str, demo: BindReport
) -> None:
    """`--theme default` is how you get the built-in look back on one render,
    so it must restate the base sheet rather than merely differ from a theme."""
    styled = html.render(demo_doc, demo, theme=theme.resolve("default"))
    overrides = by_selector(theme.resolve("default").css())
    base = by_selector(STYLESHEET)
    for name, value in overrides[":root"].items():
        assert base[":root"][name] == value
    assert "--rail-w" not in overrides[":root"]
    assert "backdraft/artifact-v1" in styled


# ---- what compiles ----------------------------------------------------------


def test_only_what_the_file_sets_is_overridden() -> None:
    css = load('[colors]\nink = "#111111"\n').css()
    assert css == ":root{--ink:#111111}"


def test_declaration_order_follows_the_allowlist_not_the_file() -> None:
    """Two spellings of one theme must produce one artifact."""
    forwards = load('[colors]\npaper = "#FFF"\nink = "#111"\n').css()
    backwards = load('[colors]\nink = "#111"\npaper = "#FFF"\n').css()
    assert forwards == backwards == ":root{--paper:#FFF;--ink:#111}"


def test_an_empty_theme_compiles_to_nothing() -> None:
    assert load('name = "bare"\n').css() == ""


def test_heading_family_takes_a_role_or_a_stack() -> None:
    assert "font-family:var(--mono)" in load('[headings]\nfamily = "mono"\n').css()
    assert "font-family:Georgia, serif" in load('[headings]\nfamily = "Georgia, serif"\n').css()


def test_small_caps_is_a_variant_and_clears_the_transform() -> None:
    css = load('[headings]\ncase = "small-caps"\n').css()
    assert "font-variant:small-caps" in css
    assert "text-transform:none" in css


def test_a_case_clears_the_variant() -> None:
    """Both properties every time, so switching themes leaves nothing behind."""
    css = load('[headings]\ncase = "uppercase"\n').css()
    assert "text-transform:uppercase" in css
    assert "font-variant:normal" in css


# ---- what is refused --------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ('[colours]\nink = "#111"\n', "unknown theme section 'colours'"),
        ('[colors]\ninc = "#111"\n', "unknown color 'inc'"),
        ('[fonts]\nseriff = "Georgia"\n', "unknown font 'seriff'"),
        ('[headings]\nsize = "2rem"\n', "unknown heading key 'size'"),
        ('[colors]\nink = "#GGGGGG"\n', "color 'ink' is not a CSS color"),
        ('[colors]\nink = ""\n', "color 'ink' is empty"),
        ('[colors]\nink = 17\n', "color 'ink' must be text, not int"),
        ('[headings]\ncase = "Small Caps"\n', "heading case must be one of"),
        ('[headings]\nweight = 1200\n', "heading weight must be a number from 100 to 900"),
        ('[headings]\nweight = "bold"\n', "heading weight must be a number from 100 to 900"),
        ('[headings]\ntracking = "wide"\n', "heading tracking is not a length"),
        ('colors = "warm"\n', "[colors] must be a table"),
        ("[colors\n", "not valid TOML"),
        ('name = ""\n', "name must be a non-empty string"),
    ],
)
def test_a_malformed_theme_says_what_is_wrong(body: str, says: str) -> None:
    with pytest.raises(theme.ThemeError) as caught:
        load(body)
    assert says in str(caught.value)


def test_theme_errors_are_domain_errors() -> None:
    """So `guard` maps them to exit 1 like every other failure, in one place."""
    assert issubclass(theme.ThemeError, BackdraftError)


def test_a_value_cannot_close_the_declaration_or_the_element() -> None:
    for hostile in ("#111;}</style><script>x", "#111} .claim{display:none"):
        with pytest.raises(theme.ThemeError, match="may not carry"):
            load(f'[colors]\nink = "{hostile}"\n')


def test_a_font_cannot_reach_the_network() -> None:
    with pytest.raises(theme.ThemeError, match="fetches nothing"):
        load('[fonts]\nserif = "url(https://fonts.example/x.woff2)"\n')


def test_a_comment_marker_is_refused() -> None:
    with pytest.raises(theme.ThemeError, match="may not carry"):
        load('[colors]\nink = "#111/*"\n')


def test_a_value_longer_than_a_line_is_refused() -> None:
    with pytest.raises(theme.ThemeError, match="longer than"):
        load(f'[fonts]\nserif = "{"Georgia," * 40}serif"\n')


# ---- resolution -------------------------------------------------------------


def test_an_unknown_name_names_the_bundled_ones() -> None:
    with pytest.raises(theme.ThemeError) as caught:
        theme.resolve("dusk")
    assert "default, press, slate" in str(caught.value)


def test_a_path_beats_the_bundled_name_when_it_has_a_suffix(tmp_path) -> None:
    written = tmp_path / "slate.toml"
    written.write_text('[colors]\nink = "#010203"\n', encoding="utf-8")
    resolved = theme.resolve(str(written))
    assert resolved.variables == {"ink": "#010203"}


def test_a_broken_theme_file_names_itself(tmp_path) -> None:
    written = tmp_path / "mine.toml"
    written.write_text('[colors]\nink = "#GG"\n', encoding="utf-8")
    with pytest.raises(theme.ThemeError) as caught:
        theme.resolve(str(written))
    assert str(written) in str(caught.value)


def test_a_theme_that_cannot_be_read_says_so_rather_than_raising_oserror(
    tmp_path,
) -> None:
    """A path that resolves but will not open — a directory here, a permission
    or an encoding elsewhere. It is a `ThemeError` like every other theme
    failure, so `guard` reports it and `render` writes nothing."""
    directory = tmp_path / "theme.toml"
    directory.mkdir()
    with pytest.raises(theme.ThemeError, match="cannot read theme"):
        theme.load(directory)


def test_the_project_theme_outranks_the_user_wide_one(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "config"
    (home / "backdraft").mkdir(parents=True)
    (home / "backdraft" / "theme.toml").write_text('[colors]\nink = "#AAAAAA"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))

    project = tmp_path / "project"
    (project / ".backdraft").mkdir(parents=True)
    (project / ".backdraft" / "theme.toml").write_text('[colors]\nink = "#BBBBBB"\n')

    assert theme.resolve(project_root=project).variables == {"ink": "#BBBBBB"}
    assert theme.resolve(project_root=tmp_path / "elsewhere").variables == {"ink": "#AAAAAA"}


def test_nothing_configured_resolves_to_the_built_in_look(tmp_path) -> None:
    assert theme.resolve(project_root=tmp_path) is None


def test_the_user_config_directory_follows_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/somewhere/cfg")
    assert str(theme.user_config_dir()) == "/somewhere/cfg/backdraft"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert theme.user_config_dir().parts[-2:] == (".config", "backdraft")
