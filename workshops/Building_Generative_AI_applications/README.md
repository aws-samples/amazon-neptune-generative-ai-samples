# Building Generative AI applications using knowledge graphs in Amazon Neptune

**Note** - This workshop currently only works in the us-west-2 region

In this workshop, you'll learn how to leverage generative AI and graphs to create an application that queries your domain-specific, differentiated, and highly related datasets using natural language. Amazon Neptune will store your knowledge graph, ensuring that the data is up-to-date and accessible. The application will use natural language processing and vector search techniques to retrieve relevant information from your knowledge graph. 

To participate, bring a laptop. This workshop is for development teams, software engineers, architects, system administrators, data engineers, and data scientists who want to build knowledge systems using AI and graphs. The workshop will last approximately 2 hours, although with the optional content it may take longer.  This workshop can only be run using Workshop Studio in the us-west-2 region.

Throughout this workshop we will be playing the part of a builder on an internal security team where you are assigned to work on a high priority project to provide tooling to provide improve your security posture through exposing software dependencies and vulnerabilities using Software Bill of Materials (SBOMs).

As a builder, you need to develop a tool that enables both power and standard users to access the information in the database through a chatbot interface. This information consists of data as well as documents.

You have decided that a graph database is the right tool to store your SBOM data and that you would like to use a generative AI application to query the documents.

The application you are building has the following requirements

* As a power user I want to be able to ask a natural language question over any data in the system
* As a user I want to be able to ask natural language question and have the system query based on a set of allowable actions
* As a user I want to be able to be able to ask a natural language question about data in documents


To meet these goals, you will use several techniques that leverage Generative AI, specifically open and defined domain question answering and graph enhanced RAG, along with services and tools such as Amazon Neptune, Amazon Bedrock, LlamaIndex, and Streamlit to build out a chatbot application. 

Throughout this workshop you will work through building the pieces required for each of the requirements above. At the end of each step, we will apply the techniques learned to an "incomplete" version of the chatbot application.

## Our Notebooks for this workshop

Each notebook is purpose-built to guide you through one of the key concepts required to build the application.

* 1-Introduction - This notebook provides an introductory overview to the application we are building as well as some introduction to graph concepts you will need to know to successfully complete this application.  
* 2-Open-Domain-Question-Answering - This notebook covers the ability to generate and execute graph queries from natural language questions.  Given the open nature of the questions allowed by this technique the user may ask any question of the system, providing a highly flexible, yet less secure, mechanism for accessing data.  e.g. Find me the number of vulnerabilities?
* 3-Defined-Domain-Question-Answering - This notebook covers to the process to take a natural language question, map it to one of a set of predefined actions, extract any key entities/identifiers from the question, and then use those as input to a pre-configured query.  This technique can be thought of as sort of a phone tree, where the user can make any request they would like but only a small set of actions are allowed.  Given the defined nature of the actions allowed, this technique allows the user ask any question but only perform a set of actions allowed by the developers, providing a secure and optimized experience for the end user.  e.g. Find me information about openldap?
* 4-Graph-Enhanced-RAG - This notebook covers how you can enhance vector-based retrieval in a RAG application through the addition of a graph.  We will show how you can leverage graphs to provide more complete and explainable responses to questions that require facts from multiple documents to answer questions or to summarize collections of documents.  e.g My vendor isn't giving me an SBOM, what do I do now?
* 5-Glossary - This notebook provides an in-depth overview of some of the key concepts and terms used throughout this workshop, to enable you to dive further into concepts that are unfamiliar or interesting.  e.g. What is a knowledge graph?

Notebooks 2, 3, and 4 contain both a walkthrough section as well as an optional section, which you can feel free to complete as time and interest allow.  The optional sections are not required to complete the workshop but do go into more depth on different configurations, optimizations, and features of these techniques.


## Prerequisites

To run this workshop you need to first enable the following models in Amazon Bedrock for your account in `us-west-2` following the directions [here](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html).

* Amazon Titan Text Embeddings V2
* Anthropic Claude 3 Sonnet

## Getting Started

To get started we have provided a Cloudformation template that will create the required infrastructure, 2 32mNCU Neptune Analytics graphs and 1 Neptune Notebook. The template is available [here](./workshop.yml) and can be executed following the steps [here](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack.html).  Please ensure that you name the stack `workshop` or portions of the notebook may not function correctly when trying to retrieve the completed application.