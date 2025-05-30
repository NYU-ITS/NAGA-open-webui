# import streamlit as st
# from langchain.schema import HumanMessage, AIMessage
# from src.llm_client import get_llm, get_embedding_model, read_yaml_as_dict
# from src.vectorstore_loader import build_facilities_vectorstore
# from src.prompt_templates import NSF_FACILITIES_WRITER
# from langchain.prompts import PromptTemplate
# from langchain.chains import RetrievalQA
# from src.memory_manager import MemoryManager
# from langchain.tools.tavily_search import TavilySearchResults
# from src.reranker import Reranker


# # ─── Page Config ───────────────────────────────────────────────────────────────
# st.set_page_config(page_title="NSF Facilities Writer", layout="wide")
# st.title("NSF Facilities Section Generator")

# config = read_yaml_as_dict("src/config.yaml")
# tavily_key = config["tavily"]["TAVILY_API_KEY"]
# search_tool = TavilySearchResults(k=3, tavily_api_key=tavily_key)

# def site_search_summary(user_query: str) -> str:
#     if "nyu" in user_query.lower():
#         result = search_tool.run(f"site:nyu.edu {user_query}")
#         return f"\n\n🔍 Web result from nyu.edu:\n{result}" if result else ""
#     elif "nsf" in user_query.lower():
#         result = search_tool.run(f"site:nsf.gov {user_query}")
#         return f"\n\n🔍 Web result from nsf.gov:\n{result}" if result else ""
#     return ""

# # ─── Session State Defaults ────────────────────────────────────────────────────
# if "memory" not in st.session_state:
#     st.session_state.memory = MemoryManager()
# if "chat_history" not in st.session_state:
#     st.session_state.chat_history = []
# if "vectorstore" not in st.session_state:
#     with st.spinner("Loading knowledge base..."):
#         embeddings = get_embedding_model()
#         st.session_state.vectorstore = build_facilities_vectorstore(
#             embedding_model=embeddings,
#             pdf_dir="data/NSF_pdfs",
#             persist_path="facilities_chroma_db",
#             chunk_size=1500,
#             chunk_overlap=300
#         )
# if "draft_generated" not in st.session_state:
#     st.session_state.draft_generated = False
# if "project_details" not in st.session_state:
#     st.session_state.project_details = {}

# # ─── Sidebar Form ──────────────────────────────────────────────────────────────
# with st.sidebar:
#     st.header("Project Details")
#     with st.form("project_info_form"):
#         title = st.text_input("Project Title")
#         space = st.text_area("Research Space")
#         instruments = st.text_area("Core Instruments")
#         compute = st.text_area("Computing Resources")
#         shared = st.text_area("Shared Facilities")
#         special = st.text_area("Special Infrastructure")
#         submitted = st.form_submit_button("Generate Draft", type="primary")

# # ─── Main Columns ──────────────────────────────────────────────────────────────
# col1 = st.container()

# if submitted:
#     st.session_state.project_details = {
#         "title": title,
#         "space": space,
#         "instruments": instruments,
#         "compute": compute,
#         "shared": shared,
#         "special": special,
#     }

#     query = "\n".join([
#         f"Project Title: {title}",
#         f"Research Space: {space}",
#         f"Core Instruments: {instruments}",
#         f"Computing Resources: {compute}",
#         f"Shared Facilities: {shared}",
#         f"Special Infrastructure: {special}"
#     ])

#     retriever = st.session_state.vectorstore.as_retriever(search_kwargs={"k": 5})
#     prompt = PromptTemplate(template=NSF_FACILITIES_WRITER, input_variables=["context", "question"])
#     llm = get_llm()
#     chain = RetrievalQA.from_chain_type(
#         llm=llm,
#         retriever=retriever,
#         chain_type="stuff",
#         chain_type_kwargs={"prompt": prompt},
#     )

#     retrieved_docs = retriever.get_relevant_documents(query)
    
#     top_doc = retrieved_docs[0].page_content if retrieved_docs else ""
#     score_proxy = len(top_doc.strip()) / 1000

#     if not retrieved_docs or score_proxy < 0.2:
#         #st.warning("⚠️ Weak internal match. Augmenting with web content...")
#         query += site_search_summary(query)

#     try:
#         raw = chain.run(query)
#         draft = raw["content"] if isinstance(raw, dict) and "content" in raw else str(raw)
#     except Exception as e:
#         st.error(f"Error generating draft: {e}")
#         st.stop()

#     st.session_state.chat_history.append({"role": "assistant", "content": draft})
#     st.session_state.memory.add_interaction(query, draft)
#     st.session_state.draft_generated = True

#     with col1:
#         st.subheader("Generated Draft")
#         st.markdown(draft)
#         with st.expander("Reference Documents"):
#             for i, doc in enumerate(retrieved_docs[:3]):
#                 st.markdown(f"**Doc {i+1}**")
#                 st.caption(doc.page_content[:500] + "...")

#     # with col2:
#     #     st.subheader("Interactive Editor")
#     #     edited = st.text_area("Refine the draft", value=draft, height=500)
#     #     if st.button("Save Edits"):
#     #         st.session_state.chat_history.append({"role": "assistant", "content": edited})
#     #         st.success("Draft saved!")

# # ─── Chat History ──────────────────────────────────────────────────────────────
# st.divider()
# st.subheader("Revision History")
# for msg in st.session_state.chat_history[-3:]:
#     with st.chat_message(msg["role"]):
#         st.markdown(msg["content"])

# # ─── Follow-up Chat ────────────────────────────────────────────────────────────
# if st.session_state.draft_generated:
#     follow_up = st.chat_input("Refine or ask follow-up...")
#     if follow_up:
#         st.session_state.chat_history.append({"role": "user", "content": follow_up})
#         with st.chat_message("user"):
#             st.markdown(follow_up)

#         messages = []
#         for msg in st.session_state.chat_history:
#             role = msg["role"]
#             content = msg["content"]
#             messages.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))

#         injected = site_search_summary(follow_up)
#         if injected:
#             messages.append(HumanMessage(content=f"{follow_up}\n\n{injected}"))

#         try:
#             reply = get_llm()(messages).content
#         except Exception as e:
#             reply = f"Error: {e}"

#         st.session_state.chat_history.append({"role": "assistant", "content": reply})
#         st.session_state.memory.add_interaction(follow_up, reply)

#         with st.chat_message("assistant"):
#             st.markdown(reply)

import streamlit as st
from langchain.schema import HumanMessage, AIMessage
from src.llm_client import get_llm, get_embedding_model, read_yaml_as_dict
from src.vectorstore_loader import build_facilities_vectorstore
from src.prompt_templates import NSF_FACILITIES_WRITER
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from src.memory_manager import MemoryManager
from langchain.tools.tavily_search import TavilySearchResults
from src.reranker import Reranker

# ─── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="NSF Facilities Writer", layout="wide")
st.title("NSF Facilities Section Generator")

config = read_yaml_as_dict("src/config.yaml")
tavily_key = config["tavily"]["TAVILY_API_KEY"]
search_tool = TavilySearchResults(k=3, tavily_api_key=tavily_key)

def site_search_summary(user_query: str) -> str:
    if "nyu" in user_query.lower():
        result = search_tool.run(f"site:nyu.edu {user_query}")
        return f"\n\n🔍 Web result from nyu.edu:\n{result}" if result else ""
    elif "nsf" in user_query.lower():
        result = search_tool.run(f"site:nsf.gov {user_query}")
        return f"\n\n🔍 Web result from nsf.gov:\n{result}" if result else ""
    return ""

# ─── Session State Defaults ────────────────────────────────────────────────────
if "memory" not in st.session_state:
    st.session_state.memory = MemoryManager()
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "vectorstore" not in st.session_state:
    with st.spinner("Loading knowledge base..."):
        embeddings = get_embedding_model()
        st.session_state.vectorstore = build_facilities_vectorstore(
            embedding_model=embeddings,
            pdf_dir="data/NSF_pdfs",
            persist_path="facilities_chroma_db",
            chunk_size=1500,
            chunk_overlap=300
        )
if "draft_generated" not in st.session_state:
    st.session_state.draft_generated = False
if "project_details" not in st.session_state:
    st.session_state.project_details = {}

# ─── Sidebar Form ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Project Details")
    with st.form("project_info_form"):
        title = st.text_input("Project Title")
        space = st.text_area("Research Space")
        instruments = st.text_area("Core Instruments")
        compute = st.text_area("Computing Resources")
        shared = st.text_area("Shared Facilities")
        special = st.text_area("Special Infrastructure")
        submitted = st.form_submit_button("Generate Draft", type="primary")

# ─── Main Columns ──────────────────────────────────────────────────────────────
col1 = st.container()

if submitted:
    st.session_state.project_details = {
        "title": title,
        "space": space,
        "instruments": instruments,
        "compute": compute,
        "shared": shared,
        "special": special,
    }

    query = "\n".join([
        f"Project Title: {title}",
        f"Research Space: {space}",
        f"Core Instruments: {instruments}",
        f"Computing Resources: {compute}",
        f"Shared Facilities: {shared}",
        f"Special Infrastructure: {special}"
    ])

    retriever = st.session_state.vectorstore.as_retriever(search_kwargs={"k": 10})
    raw_docs = retriever.get_relevant_documents(query)

    reranker = Reranker()
    retrieved_docs = reranker.rerank(query, raw_docs, strategy="cross-encoder", top_k=5)

    top_doc = retrieved_docs[0].page_content if retrieved_docs else ""
    score_proxy = len(top_doc.strip()) / 1000

    if not retrieved_docs or score_proxy < 0.2:
        query += site_search_summary(query)

    llm = get_llm()
    prompt = PromptTemplate(template=NSF_FACILITIES_WRITER, input_variables=["context", "question"])
    chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": prompt},
    )

    try:
        raw = chain.run(query)
        draft = raw["content"] if isinstance(raw, dict) and "content" in raw else str(raw)
        validated = reranker.validate_response(llm=llm, response=draft, reference_docs=retrieved_docs)
    except Exception as e:
        st.error(f"Error generating or validating draft: {e}")
        st.stop()

    st.session_state.chat_history.append({"role": "assistant", "content": validated})
    st.session_state.memory.add_interaction(query, validated)
    st.session_state.draft_generated = True

    with col1:
        st.subheader("NSF Facilities Draft Output")

        with st.expander("📝 Validated Version (Final) — Click to view"):
            st.markdown(validated)

        with st.expander("🔍 Original LLM Draft (Before Validation)"):
            st.markdown(draft)

        with st.expander("Reference Documents"):
            for i, doc in enumerate(retrieved_docs[:3]):
                st.markdown(f"**Doc {i+1}**")
                st.caption(doc.page_content[:500] + "...")

# ─── Chat History ──────────────────────────────────────────────────────────────
st.divider()
st.subheader("Revision History")
for msg in st.session_state.chat_history[-3:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ─── Follow-up Chat ────────────────────────────────────────────────────────────
if st.session_state.draft_generated:
    follow_up = st.chat_input("Refine or ask follow-up...")
    if follow_up:
        st.session_state.chat_history.append({"role": "user", "content": follow_up})
        with st.chat_message("user"):
            st.markdown(follow_up)

        messages = []
        for msg in st.session_state.chat_history:
            role = msg["role"]
            content = msg["content"]
            messages.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))

        injected = site_search_summary(follow_up)
        if injected:
            messages.append(HumanMessage(content=f"{follow_up}\n\n{injected}"))

        try:
            reply = get_llm()(messages).content
        except Exception as e:
            reply = f"Error: {e}"

        st.session_state.chat_history.append({"role": "assistant", "content": reply})
        st.session_state.memory.add_interaction(follow_up, reply)

        with st.chat_message("assistant"):
            st.markdown(reply)
