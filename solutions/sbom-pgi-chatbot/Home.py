"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import streamlit as st

st.set_page_config(
    page_title="Neptune Generative AI Demo",
    page_icon="🔱",
    layout="wide",
)

st.write("## Analyze Software Bill Of Materials (SBOM)")
st.write("### Using Generative AI with Amazon Neptune and Amazon Bedrock")

st.sidebar.success("Select a demo above.")

st.markdown(
    """
    Select a demo from the sidebar to see some examples
    of how you can use Generative AI and Knowledge Graphs to analyze SBOMs!
    
    ### Want to learn more?
    
    - Click `Open Domain Question Answering` to see how Amazon Bedrock can convert natural language questions into 
    openCypher queries run on Amazon Neptune
    - Click `Defined Domain Question Answering` to see how to use Amazon Bedrock to extract key entities from natural 
    language questions, which are then used to run templated queries
    - Click `Knowledge Graph Enhanced RAG` to see how you can combine Knowledge Graphs with RAG applications to add 
    domain knowledge to a RAG application to provide more complete and explainable answers
"""
)

st.write("### What is a Software Bill Of Materials (SBOM)")

st.markdown(
    """
    A software bill of materials (SBOM) is a critical component of software development and management, helping 
    organizations to improve the transparency, security, and reliability of their software applications. An SBOM acts 
    as an "ingredient list" of libraries and components of a software application that:

Enables software creators to track dependencies within their applications
Provides security personnel the ability to examine and assess the risk of potential vulnerabilities within an 
environment
Provides legal personnel with the information needed to assure that a particular software is in compliance with all 
licensing requirements.
"""
)

st.write("### SBOM Graph Schema")
st.image("images/schema.png", use_column_width=True)
