# Architecture

{{One paragraph: what kind of system this is and how it is put together. Link to [adr/](adr/README.md) for why.}}

## Components

```mermaid
flowchart LR
    A[{{component-a}}] --> B[{{component-b}}]
    B --> C[{{component-c}}]
```

{{One short paragraph or table per component: responsibility and location.}}

## {{Main flow, e.g. One request, One run}}

{{Walk through the most important flow step by step, with a sequence diagram if it helps.}}

## Building blocks

| Block | Responsibility | Where |
|---|---|---|
| {{block-1}} | {{what it does}} | `{{path}}` |

## Data flow

{{What data enters, how it is transformed and stored, what leaves.}}

## Trust boundaries

| Boundary | What enforces it |
|---|---|
| {{what must not happen}} | {{mechanism, and the test that checks it}} |
