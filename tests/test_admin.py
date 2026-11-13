"""Back-office : la page Données n'est accessible qu'avec le mot de passe de st.secrets["ADMIN_PASSWORD"]."""
from pathlib import Path

import pytest
import streamlit as st
from streamlit.runtime.context import ContextProxy
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

APP = str(Path(__file__).resolve().parents[1] / "src" / "edgecourt" / "ui" / "app.py")
LOCKED = "Trop de tentatives — réessayez dans 15 minutes"


@pytest.fixture(autouse=True)
def fresh_attempt_counter():
    st.cache_resource.clear()  # le compteur d'essais est partagé par le processus : chaque test repart de zéro
    yield
    st.cache_resource.clear()


def enter(at: AppTest):
    return next(b for b in at.button if b.label == "Entrer")  # bouton du formulaire admin (l'en-tête a aussi des boutons)


def submit(at: AppTest, pw: str) -> AppTest:
    at.text_input[0].input(pw)
    return enter(at).click().run()


@pytest.fixture(autouse=True)
def visitor(monkeypatch):
    """Simule le visiteur : IP de la connexion et en-tête X-Forwarded-For (modifiables en cours de test).
    Autouse : sous AppTest, l'IP brute est un MagicMock différent à chaque exécution (chaque essai = nouveau visiteur)."""
    who = {"ip": "203.0.113.1", "xff": None}
    monkeypatch.setattr(ContextProxy, "ip_address", property(lambda self: who["ip"]))
    monkeypatch.setattr(ContextProxy, "headers", property(lambda self: {"X-Forwarded-For": who["xff"]} if who["xff"] else {}))
    return who


def admin_app(secret: str | None, **more_secrets) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    if secret is not None:
        at.secrets["ADMIN_PASSWORD"] = secret
    for k, v in more_secrets.items():
        at.secrets[k] = v
    at._page_hash = calc_hash("admin")  # page-fonction : hash = url_path (AppTest.switch_page ne gère que les fichiers)
    return at.run()


def subheaders(at):
    return [s.value for s in at.subheader]


def test_admin_not_configured_shows_only_message():
    at = admin_app("")  # secret vide = non configuré (indépendant d'un .streamlit/secrets.toml local)
    assert [i.value for i in at.info] == ["Accès admin non configuré"]
    assert not at.text_input and "Connecteurs" not in subheaders(at)


def test_admin_wrong_password_hides_data_and_correct_password_shows_it():
    at = admin_app("t3st-only")
    assert not at.exception and "Connecteurs" not in subheaders(at)
    at.text_input[0].input("mauvais")
    enter(at).click().run()
    assert [e.value for e in at.error] == ["Mot de passe incorrect."] and "Connecteurs" not in subheaders(at)
    at.text_input[0].input("t3st-only")
    enter(at).click().run()
    assert not at.exception and "Connecteurs" in subheaders(at)


def test_admin_blocks_after_5_wrong_attempts_and_hides_form_even_after_reload():
    at = admin_app("t3st-only")
    for _ in range(4):
        submit(at, "mauvais")
        assert [e.value for e in at.error] == ["Mot de passe incorrect."]
    submit(at, "mauvais")                                   # 5e essai faux → blocage
    assert [e.value for e in at.error] == [LOCKED] and not at.text_input
    again = admin_app("t3st-only")                          # nouvelle session (rechargement) : toujours bloqué
    assert [e.value for e in again.error] == [LOCKED] and not again.text_input
    assert "Connecteurs" not in subheaders(again)


def test_correct_password_resets_the_counter():
    at = admin_app("t3st-only")
    for _ in range(4):
        submit(at, "mauvais")
    submit(at, "t3st-only")
    assert "Connecteurs" in subheaders(at)
    other = admin_app("t3st-only")                          # compteur remis à zéro : 4 nouveaux essais faux ne bloquent pas
    for _ in range(4):
        submit(other, "mauvais")
    assert [e.value for e in other.error] == ["Mot de passe incorrect."] and other.text_input


def lock_out(**secrets) -> None:
    at = admin_app("t3st-only", **secrets)
    for _ in range(5):
        submit(at, "mauvais")
    assert [e.value for e in at.error] == [LOCKED]


def test_block_is_per_visitor(visitor):
    lock_out()                                              # le visiteur A se fait bloquer
    visitor["ip"] = "198.51.100.7"                          # le visiteur B n'est pas bloqué et peut entrer
    b = admin_app("t3st-only")
    assert not b.error and b.text_input
    submit(b, "t3st-only")
    assert "Connecteurs" in subheaders(b)
    visitor["ip"] = "203.0.113.1"                           # A reste bloqué (rechargement), même après la connexion de B
    a = admin_app("t3st-only")
    assert [e.value for e in a.error] == [LOCKED] and not a.text_input


def test_behind_trusted_proxy_uses_forwarded_ip_and_ignores_client_spoofing(visitor):
    visitor["ip"] = "10.0.0.1"                              # toutes les connexions viennent du proxy
    visitor["xff"] = "203.0.113.1"                          # IP du visiteur A ajoutée par le proxy
    lock_out(ADMIN_TRUSTED_PROXIES=1)
    visitor["xff"] = "198.51.100.7"                         # B, derrière le même proxy : pas bloqué
    b = admin_app("t3st-only", ADMIN_TRUSTED_PROXIES=1)
    assert not b.error and b.text_input
    visitor["xff"] = "198.51.100.99, 203.0.113.1"           # A tente de se faire passer pour un autre : la dernière IP (proxy) compte
    a = admin_app("t3st-only", ADMIN_TRUSTED_PROXIES=1)
    assert [e.value for e in a.error] == [LOCKED]


def test_public_navigation_has_no_data_link():
    at = AppTest.from_file(APP, default_timeout=120).run()
    labels = [p.proto.label or p.proto.page for p in at.get("page_link")]
    assert "Données" not in labels and labels.count("Admin") == 1
