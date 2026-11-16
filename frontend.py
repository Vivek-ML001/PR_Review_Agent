import streamlit as st
from backend import run_review

st.set_page_config(page_title="PR Review Agent", page_icon="🤖 ", layout="centered")
st.title("🤖 PR Review Agent")
st.caption("Enter a GitHub PR URL to generate an automated AI review (Security, Bugs, Tests, Lint)")

url = st.text_input("GitHub PR URL", placeholder="https://github.com/owner/repo/pull/1")
post = st.checkbox("Post review directly as a GitHub PR comment")

if st.button("Review", type="primary"):
    if not url.strip():
        st.warning("Pehle PR URL daalo")
    else:
        try:
            with st.spinner("Reviewing... (10-30 sec)"):
                review, posted = run_review(url, post=post)

            if review is None:
                st.info("Docs-only PR, review skip")
            else:
                st.markdown(review)
                if post:
                    if posted:
                        st.success("Comment PR pe post ho gaya ✅")
                    else:
                        st.error("Post fail hua, token ka Pull requests write permission check karo")
        except Exception as e:
            st.error(str(e))



            
