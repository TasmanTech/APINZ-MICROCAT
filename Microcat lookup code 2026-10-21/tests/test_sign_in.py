# -*- coding: utf-8 -*-
r"""
AUTO SIGN-IN: LOUD WHEN IT CANNOT, ONCE WHEN REFUSED.  31 Oct 2026 (Morgan).

The rules from 28 Oct 2026: no credentials means it SAYS so; a refused login
is recorded and not resubmitted every pass (that locks the account a person
also uses); success is the Start tile, nothing less. No real password is used
anywhere here - the .env is written into tmp_path.
"""
import json

import fakes


def write_env(env, user="robot", pwd="pw"):
    (env.tmp / ".env").write_text(
        f"# test\nMICROCAT_USERNAME={user}\nMICROCAT_PASSWORD='{pwd}'\n", encoding="utf-8")


# ---------------------------------------------------------------- credentials
def test_no_credentials_means_none(env):
    assert env.opened()._credentials() == ()


def test_the_example_text_is_not_a_login(env):
    write_env(env, user="your username", pwd="your password")
    assert env.opened()._credentials() == ()


def test_credentials_from_env_file_quotes_stripped(env):
    write_env(env)
    assert env.opened()._credentials() == ("robot", "pw")


def test_a_real_environment_variable_wins(env, monkeypatch):
    write_env(env)
    monkeypatch.setenv("MICROCAT_USERNAME", "from-env")
    monkeypatch.setenv("MICROCAT_PASSWORD", "x")
    assert env.opened()._credentials() == ("from-env", "x")


def test_the_password_never_goes_to_disk(env):
    write_env(env, pwd="s3cret-value")
    mc = env.opened()
    mc._record_refusal(mc._cred_stamp("robot"), "test")
    assert "s3cret" not in (env.tmp / "refused.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------- sign_in()
def test_skipped_sign_in_is_loud(env):
    env.world = fakes.World(signed_in=False)
    assert env.opened().sign_in() is False
    assert "AUTO SIGN-IN SKIPPED" in env.log()


def test_already_signed_in_is_success(env):
    write_env(env)
    env.world = fakes.World(signed_in=True)
    assert env.opened().sign_in() is True


def test_good_login_signs_in(env):
    write_env(env)
    env.world = fakes.World(signed_in=False)
    env.Microcat.first_page = lambda ctx: fakes.LoginPage(ctx, accept=True)
    mc = env.opened()
    assert mc.sign_in() is True
    assert "signed in to Microcat automatically" in env.log()
    assert not (env.tmp / "refused.json").exists()


def test_refused_login_is_recorded_once(env, monkeypatch):
    write_env(env)
    env.world = fakes.World(signed_in=False)
    env.Microcat.first_page = lambda ctx: fakes.LoginPage(ctx, accept=False)
    clock = iter(range(0, 10_000, 5))                 # the 45 s wait, without waiting
    monkeypatch.setattr(env.mr.time, "time", lambda: next(clock))
    mc = env.opened()
    assert mc.sign_in() is False
    refused = json.loads((env.tmp / "refused.json").read_text(encoding="utf-8"))
    assert "refused" in refused["why"]

    # the next pass must NOT type the same password again
    page = fakes.LoginPage(mc.ctx, accept=True)       # would succeed if it tried
    mc.page = page
    assert mc.sign_in() is False
    assert page.typed == {}, "resubmitted a refused login"
    assert "NOT RETRIED" in env.log()


def test_saving_the_env_again_lifts_the_refusal(env):
    write_env(env)
    mc = env.opened()
    mc._record_refusal("robot|0", "old refusal")       # stamped against an older .env
    env.world.signed_in = True
    assert mc.sign_in() is True
    assert not (env.tmp / "refused.json").exists()


def test_a_page_without_login_words_is_not_signed_in_by_assumption(env):
    # 28 Oct 2026: success is the Start tile, not "no login words on screen"
    write_env(env)
    env.world = fakes.World(signed_in=False)
    mc = env.opened()                                  # landing page, no Start, no form
    assert mc.sign_in() is False
    assert "neither a login page nor a session" in env.log()
