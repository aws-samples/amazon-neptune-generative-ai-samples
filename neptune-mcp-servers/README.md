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

## Connecting to Neptune from a Local machine
To connect to your Neptune instance the machine that your MCP server is running on needs to have access to reach your Neptune instance.

When connecting the graph notebook to Neptune via a private endpoint, make sure you have a network setup to communicate to the VPC that Neptune runs on. If not, you can follow this [guide](https://github.com/aws/graph-notebook/tree/main/additional-databases/neptune).

If you are using Neptune Analytics this can achive this through enabling public connectivity as shown in this [guide](https://docs.aws.amazon.com/neptune-analytics/latest/userguide/gettingStarted-connecting.html).
