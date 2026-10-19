"""Streamlit client for the HorRAGor FastAPI service."""

from __future__ import annotations

import uuid
from typing import Any

import streamlit as st

from src.logging_config import configure_logging
from src.ui import ApiClientError, HorragorApiClient

configure_logging("streamlit-ui")


st.set_page_config(
    page_title="HorRAGor BOT",
    page_icon="👻",
    layout="wide",
)


def get_api_client() -> HorragorApiClient:
    """Return a client scoped to this Streamlit browser session."""
    if "api_client" not in st.session_state:
        st.session_state.api_client = HorragorApiClient.from_environment()
    return st.session_state.api_client


def check_api_health() -> dict[str, Any] | None:
    """Return the API health payload, or None when the API is unreachable."""
    return get_api_client().check_health()


def ask_api(
    question: str,
    history: list[dict[str, str]] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Send a question to FastAPI and return its validated JSON response."""
    return get_api_client().ask(
        question,
        history=history,
        session_id=session_id,
    )


def new_conversation() -> dict[str, Any]:
    return {"title": "Nouvelle conversation", "messages": []}


if "conversations" not in st.session_state:
    st.session_state.conversations = {"chat_1": new_conversation()}

if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = "chat_1"


def get_messages() -> list[dict[str, Any]]:
    return st.session_state.conversations[st.session_state.current_chat_id]["messages"]


def render_verdict(verdict: dict[str, Any] | None) -> None:
    if not isinstance(verdict, dict):
        return

    is_valid = verdict.get("is_valid")
    score = verdict.get("score", "-")
    label = "Réponse validée" if is_valid else "Réponse non validée"
    st.caption(f"{label} · score {score}/10")

    justification = verdict.get("justification")
    if justification:
        st.caption(str(justification))


def render_token_usage(token_usage: dict[str, Any] | None) -> None:
    if not isinstance(token_usage, dict):
        return

    counts = {
        key: token_usage.get(key)
        for key in ("input", "output", "total")
    }
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in counts.values()):
        return
    st.caption(
        f"Tokens · input {counts['input']} · output {counts['output']} · total {counts['total']}"
    )


def render_matches(matches: list[dict[str, Any]] | None) -> None:
    if not matches:
        return

    with st.expander("Films retrouvés dans FAISS"):
        for match in matches:
            title = match.get("title", "Titre inconnu")
            movie_id = match.get("id", "-")
            score = match.get("score", 0.0)
            st.write(f"{title} · ID {movie_id} · score {float(score):.3f}")


st.markdown(
    """
    <style>
    .main-title {
        text-align: center;
        font-size: 42px;
        color: #8b0000;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .subtitle {
        text-align: center;
        color: #bcbcbc;
        margin-bottom: 25px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="main-title">👻 HorRAGor BOT</div>
    <div class="subtitle">Votre expert IA du cinéma d'horreur</div>
    """,
    unsafe_allow_html=True,
)

api_client = get_api_client()
health: dict[str, Any] | None = None
auth_required = False

with st.sidebar:
    st.title("🎬 HorRAGor BOT")
    st.caption(f"API: {api_client.base_url}")

    health = check_api_health()
    auth_required = bool(health and health.get("auth_enabled"))
    if health and health.get("faiss_router") == "ready":
        st.success(f"FAISS connecté · {health.get('records', '?')} films")
        model_health = health.get("narration_model") or {}
        model_name = model_health.get("model", "modèle local")
        if model_health.get("status") == "ready":
            st.caption(f"SLM actif · {model_name}")
        elif model_health.get("status") == "disabled":
            st.warning("SLM désactivé · réponses de secours")
        else:
            st.warning(f"SLM indisponible · {model_name}")
    else:
        st.error("API ou index FAISS indisponible")
        st.caption("Démarrez FastAPI avant d'envoyer une question.")

    st.divider()

    if auth_required:
        if api_client.is_authenticated:
            st.success("Session sécurisée")
            if st.button("Se déconnecter", use_container_width=True):
                api_client.logout()
                st.rerun()
        else:
            with st.form("authentication"):
                username = st.text_input("Identifiant", max_chars=128)
                password = st.text_input("Mot de passe", type="password", max_chars=1024)
                submitted = st.form_submit_button("Se connecter", use_container_width=True)
            if submitted:
                try:
                    api_client.login(username, password)
                    st.rerun()
                except ApiClientError as exc:
                    st.error(str(exc))

        st.divider()

    if st.button("➕ Nouvelle conversation", use_container_width=True):
        chat_id = str(uuid.uuid4())[:8]
        st.session_state.conversations[chat_id] = new_conversation()
        st.session_state.current_chat_id = chat_id
        st.rerun()

    st.subheader("💬 Conversations")
    for chat_id, chat_data in st.session_state.conversations.items():
        button_label = chat_data["title"] or "Nouvelle conversation"
        if st.button(button_label, key=f"chat_{chat_id}", use_container_width=True):
            st.session_state.current_chat_id = chat_id
            st.rerun()

    st.divider()
    if st.button("🗑️ Réinitialiser", use_container_width=True):
        st.session_state.conversations = {"chat_1": new_conversation()}
        st.session_state.current_chat_id = "chat_1"
        st.rerun()


for message in get_messages():
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            render_token_usage(message.get("token_usage"))
            render_verdict(message.get("verdict"))
            render_matches(message.get("matches"))


prompt = st.chat_input(
    "Pose ta question sur les films d'horreur...",
    disabled=auth_required and not api_client.is_authenticated,
)

if prompt and prompt.strip():
    question = prompt.strip()
    messages = get_messages()
    history = [
        {"role": str(message.get("role", "")), "content": str(message.get("content", ""))}
        for message in messages
        if message.get("role") in {"user", "assistant"} and message.get("content")
    ][-20:]
    if not messages:
        st.session_state.conversations[st.session_state.current_chat_id]["title"] = question[:35]

    messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"), st.spinner("👻 Le HorRAGor interroge l'API et FAISS..."):
        try:
            result = ask_api(
                question,
                history=history,
                session_id=st.session_state.current_chat_id,
            )
            answer = result["response"]
            token_usage = result.get("token_usage")
            verdict = result.get("verdict")
            metadata = result.get("metadata") or {}
            matches = metadata.get("matches")
            st.markdown(answer)
            render_token_usage(token_usage)
            render_verdict(verdict)
            render_matches(matches)
        except ApiClientError as exc:
            answer = f"Erreur API : {exc}"
            token_usage = None
            verdict = None
            matches = None
            st.error(answer)

    messages.append(
        {
            "role": "assistant",
            "content": answer,
            "token_usage": token_usage,
            "verdict": verdict,
            "matches": matches,
        }
    )