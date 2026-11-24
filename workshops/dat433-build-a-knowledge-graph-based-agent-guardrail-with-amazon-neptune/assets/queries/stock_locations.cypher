// MIT No Attribution
//
// Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
//
// Permission is hereby granted, free of charge, to any person obtaining a copy of this
// software and associated documentation files (the "Software"), to deal in the Software
// without restriction, including without limitation the rights to use, copy, modify,
// merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
// permit persons to whom the Software is furnished to do so.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
// INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
// PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
// OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
// SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
//
// SPDX-License-Identifier: MIT-0

// The graph's half of the stock check: which of one supplier's warehouses carry a
// product. verify.validation_report reads their counts from the DynamoDB stock table,
// keyed by these same ids.
// Parameters: $supplier_name, $product_name
MATCH (:Supplier {name: $supplier_name})-[:HAS_WAREHOUSE]->(w:Warehouse)
      -[:STOCKS]->(p:Product {name: $product_name})
RETURN id(w) AS warehouse_id, w.name AS warehouse, id(p) AS product_id
