# Amazon Neptune MCP Server

## 🌟 Overview

A Model Context Protocol (MCP) server for [Amazon Neptune](https://aws.amazon.com/neptune/) that supports both Neptune Database and Neptune Analytics.

## Available Servers

This repo contains the following MCP servers:

### [Neptune Query Server](./neptune-query/README.md)

A server that allows for running queries on Amazon Neptune.

- Run openCypher/Gremlin queries on a Neptune Database
- Run openCypher queries on Neptune Analytics
- Get the schema of the graph


### [Neptune Memory Server](./neptune-memory/README.md)

A basic server implementation that provides a knowledge graph based persistent memory system running on Amazon Neptune.  This allows your applications to remember information about the user and interactions across chats.