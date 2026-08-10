# Architecture Diagram

**Status:** final, Milestone 2. Reflects exactly what `AZURE_MIGRATION/terraform/` provisions — nothing aspirational, nothing from a later milestone drawn in early.

```mermaid
flowchart TB
    subgraph RG["Resource Group (rg-payreality-&lt;env&gt;-&lt;region&gt;)"]
        subgraph VNET["Virtual Network"]
            subgraph SNET_CA["Subnet: container-apps (delegated)"]
                CAE["Container Apps Environment"]
                CA["Container App: payreality-api\n(same image, same embedded OPA)"]
                CAE --- CA
            end
            subgraph SNET_PG["Subnet: postgres (delegated)"]
                PG["PostgreSQL Flexible Server\n(private access, no public endpoint)"]
            end
            subgraph SNET_PE["Subnet: private-endpoints"]
                PE_KV["Private Endpoint: Key Vault"]
                PE_ST["Private Endpoint: Blob Storage"]
            end
        end

        KV["Key Vault\n(RBAC, real + placeholder secrets)"]
        ST["Storage Account\n(uploads / evidence-exports / authorization-receipts)"]
        ACR["Container Registry\n(Standard, AAD-only)"]
        LAW["Log Analytics Workspace"]
        AI["Application Insights"]

        ID_APP["Managed Identity: runtime\n(AcrPull, Key Vault Secrets User,\nStorage Blob Data Contributor)"]
        ID_CICD["Managed Identity: CI/CD\n(AcrPush, GitHub OIDC federated)"]

        PE_KV -.-> KV
        PE_ST -.-> ST
        CA -- "reads secrets via" --> ID_APP
        ID_APP -. RBAC .-> KV
        ID_APP -. RBAC .-> ST
        ID_APP -. RBAC .-> ACR
        ID_CICD -. RBAC .-> ACR
        CA -- "pulls image" --> ACR
        CA -- "connects (private)" --> PG
        CA -- "diagnostic logs" --> LAW
        PG -- "diagnostic logs" --> LAW
        KV -- "diagnostic logs" --> LAW
        ST -- "diagnostic logs" --> LAW
        ACR -- "diagnostic logs" --> LAW
        LAW --- AI
    end

    GH["GitHub Actions\n(OIDC, no stored secret)"] -. "future: push image" .-> ID_CICD

    classDef future stroke-dasharray: 5 5
    class GH future
```

## Reading this diagram

- **Solid arrows** are wired and functional the moment Milestone 3 applies this configuration.
- **Dashed elements** (GitHub Actions) represent the CI/CD *identity trust relationship* this milestone establishes (the federated credential) — the workflow that actually uses it is not created until a later milestone, per Milestone 2's own CI/CD Preparation boundary.
- Nothing in this diagram shows DNS or the public internet reaching this Container App — that's deliberate. Ingress exists (`*.azurecontainerapps.io`, HTTPS-only) but no custom domain is bound and no production traffic reaches it until Milestone 9.
