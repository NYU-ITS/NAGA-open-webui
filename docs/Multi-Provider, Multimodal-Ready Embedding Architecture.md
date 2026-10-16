# Multi-Provider, Multimodal-Ready Embedding Architecture {#multi-provider,-multimodal-ready-embedding-architecture}

**Production Task Scope \- July** 

[**Multi-Provider, Multimodal-Ready Embedding Architecture	1**](#multi-provider,-multimodal-ready-embedding-architecture)

[1\. Purpose	3](#1.-purpose)

[**2\. Product Scope	4**](#2.-product-scope)

[2.1 In Scope	4](#2.1-in-scope)

[1\. Group-level embedding configuration	4](#1.-group-level-embedding-configuration)

[2\. Multiple embedding providers	5](#2.-multiple-embedding-providers)

[3\. Variable embedding dimensions	5](#3.-variable-embedding-dimensions)

[4\. Text and image embedding support	5](#4.-text-and-image-embedding-support)

[5\. Re-indexing when model changes	6](#5.-re-indexing-when-model-changes)

[6\. Store embedding metadata	6](#6.-store-embedding-metadata)

[2.2 Out of Scope for V1	6](#2.2-out-of-scope-for-v1)

[**3\. Key Product Decision	7**](#3.-key-product-decision)

[Group-Level Model Selection	7](#group-level-model-selection)

[Why this is recommended	7](#why-this-is-recommended)

[**4\. Embedding Versioning Decision	8**](#4.-embedding-versioning-decision)

[Recommendation: Do not build full active/inactive version management in V1	8](#recommendation:-do-not-build-full-active/inactive-version-management-in-v1)

[V1 behavior	8](#v1-behavior)

[Why not full versioning yet?	8](#why-not-full-versioning-yet?)

[What should still be stored	8](#what-should-still-be-stored)

[**5\. Functional Requirements	9**](#5.-functional-requirements)

[FR-1: Group Embedding Configuration	9](#fr-1:-group-embedding-configuration)

[FR-2: Embedding Model Registry	9](#fr-2:-embedding-model-registry)

[FR-3: Document Storage	10](#fr-3:-document-storage)

[FR-4: Chunk Storage	11](#fr-4:-chunk-storage)

[FR-5: Embedding Storage	12](#fr-5:-embedding-storage)

[FR-6: Re-indexing on Model Change	12](#fr-6:-re-indexing-on-model-change)

[FR-7: Retrieval Uses Group Model	13](#fr-7:-retrieval-uses-group-model)

[FR-8: Image Support	13](#fr-8:-image-support)

[FR-9: Provider Abstraction	14](#fr-9:-provider-abstraction)

[**6\. Non-Functional Requirements	14**](#6.-non-functional-requirements)

[NFR-1: Maintainability	14](#nfr-1:-maintainability)

[NFR-2: Scalability	15](#nfr-2:-scalability)

[NFR-3: Reliability	15](#nfr-3:-reliability)

[NFR-4: Traceability	15](#nfr-4:-traceability)

[NFR-5: Backward Compatibility	16](#nfr-5:-backward-compatibility)

[**7\. Recommended Data Model	16**](#7.-recommended-data-model)

[7.1	16](#7.1)

[embedding\_models	16](#embedding_models)

[7.2	17](#7.2)

[group\_embedding\_settings	17](#group_embedding_settings)

[7.3	17](#7.3)

[documents	17](#documents)

[7.4	18](#7.4)

[chunks	18](#chunks)

[7.5	18](#7.5)

[embeddings	18](#embeddings)

[7.6	19](#7.6)

[embedding\_jobs	19](#embedding_jobs)

[**8\. PGVector Implementation Guidance	20**](#8.-pgvector-implementation-guidance)

[Recommended approach	20](#recommended-approach)

[Practical Implementation Options	21](#practical-implementation-options)

[Option A: Separate vector tables by dimension	21](#option-a:-separate-vector-tables-by-dimension)

[Option B: Separate vector tables by model family	21](#option-b:-separate-vector-tables-by-model-family)

[Recommendation	22](#recommendation)

[**9\. Re-indexing Workflow	22**](#9.-re-indexing-workflow)

[Trigger	22](#trigger)

[Workflow	22](#workflow)

[Important Product Behavior	23](#important-product-behavior)

[Option 1: Continue using old embeddings until new indexing completes	23](#option-1:-continue-using-old-embeddings-until-new-indexing-completes)

[Option 2: Disable retrieval until re-indexing completes \[Recommended\]	23](#option-2:-disable-retrieval-until-re-indexing-completes-[recommended])

[Recommendation	23](#recommendation-1)

[Re-indexing Execution Strategy	24](#re-indexing-execution-strategy)

[Method 1: Queue Workers (Redis-backed RQ Workers)	24](#method-1:-queue-workers-\(redis-backed-rq-workers\))

[Method 2: Dedicated Kubernetes Jobs	24](#method-2:-dedicated-kubernetes-jobs)

[**10\. Admin Experience	25**](#10.-admin-experience)

[Group Admin Settings	25](#group-admin-settings)

[**11\. Permissions	26**](#11.-permissions)

[**12\. Search/RAG Behavior	27**](#12.-search/rag-behavior)

[Query flow	27](#query-flow)

[Important rule	27](#important-rule)

[**13\. Migration Plan	28**](#13.-migration-plan)

[Phase 1: Create new schema	28](#phase-1:-create-new-schema)

[Phase 2: Register current embedding model	28](#phase-2:-register-current-embedding-model)

[Phase 3: Assign existing groups to current model	28](#phase-3:-assign-existing-groups-to-current-model)

[Phase 4: Migrate or regenerate embeddings	28](#phase-4:-migrate-or-regenerate-embeddings)

[Migration	29](#migration)

[Regeneration	29](#regeneration)

[Phase 5: Add provider abstraction	29](#phase-5:-add-provider-abstraction)

[Phase 6: Add image support	29](#phase-6:-add-image-support)

[**14\. Development Scope	29**](#14.-development-scope)

[Backend Scope	30](#backend-scope)

[Required	30](#required)

[Optional for V1	30](#optional-for-v1)

[Frontend Scope	30](#frontend-scope)

[Required	30](#required-1)

[Optional	30](#optional)

[Database Scope	31](#database-scope)

[Worker/Queue Scope	31](#worker/queue-scope)

[**15\. Acceptance Criteria	31**](#15.-acceptance-criteria)

[AC-1: Existing RAG continues to work	31](#ac-1:-existing-rag-continues-to-work)

[AC-2: Group has embedding configuration	31](#ac-2:-group-has-embedding-configuration)

[AC-3: Query and document embeddings use same model	32](#ac-3:-query-and-document-embeddings-use-same-model)

[AC-4: Model change triggers re-indexing	32](#ac-4:-model-change-triggers-re-indexing)

[AC-5: Embedding metadata is stored	32](#ac-5:-embedding-metadata-is-stored)

[AC-6: Image content can be stored	32](#ac-6:-image-content-can-be-stored)

[AC-7: Failed embedding jobs are trackable	32](#ac-7:-failed-embedding-jobs-are-trackable)

[**16\. Future Scope	33**](#16.-future-scope)

[V2	33](#v2)

[V3	33](#v3)

[**17\. Final Recommended V1 Scope	33**](#17.-final-recommended-v1-scope)

[V1 should include	33](#v1-should-include)

[V1 should not include	34](#v1-should-not-include)

## **1\. Purpose** {#1.-purpose}

The current system uses PGVector with a fixed embedding model, likely `text-embedding-3-small`, and a fixed vector dimension. This works for text-based RAG but creates limitations when the platform needs to support:

* Multiple embedding providers  
* Different embedding dimensions  
* Group-level embedding model selection  
* Text and image-based retrieval  
* Future audio/video support  
* Re-indexing when embedding models change

The purpose of this enhancement is to redesign the embedding storage and indexing layer so the platform can support multiple embedding models without requiring repeated schema redesigns.

The system should remain simple enough for the current scale:

10–20 groups  
50–120 users per group  
Small-to-medium knowledge bases  
PGVector as the vector backend

The goal is not to build internet-scale search infrastructure. The goal is to make the current RAG system flexible, maintainable, and ready for multimodal expansion.

//longer duration

---

# **2\. Product Scope** {#2.-product-scope}

## **2.1 In Scope** {#2.1-in-scope}

The system shall support:

### **1\. Group-level embedding configuration** {#1.-group-level-embedding-configuration}

Each group should have one selected embedding provider and model.

Example:

Group A → OpenAI text embedding  
Group B → Gemini multimodal embedding  
Group C → future provider/model

Embedding model selection should happen at the **group level**, not per knowledge base.

---

### **2\. Multiple embedding providers** {#2.-multiple-embedding-providers}

The architecture should not assume only OpenAI embeddings.

Supported provider model should be configurable through metadata such as:

provider  
model\_name  
dimension  
modality

This allows the platform to later support OpenAI, Gemini, Anthropic, or other providers without changing the core database design.

---

### **3\. Variable embedding dimensions** {#3.-variable-embedding-dimensions}

The system should not assume a single fixed vector dimension.

**The current issue is that PGVector columns generally expect a fixed vector dimension per indexed column/table.** Therefore, the system should be designed so that different models with different dimensions can coexist structurally, even if only one active model is used per group.

---

### **4\. Text and image embedding support** {#4.-text-and-image-embedding-support}

V1 should support:

text  
image

The design should also leave room for future:

audio  
video  
multimodal

without making audio/video part of the immediate development scope.

---

### **5\. Re-indexing when model changes** {#5.-re-indexing-when-model-changes}

When a group admin changes the embedding provider/model, existing documents in that group should be re-embedded.

The system should:

1. Detect that the group embedding model changed.  
2. *Mark existing embeddings as stale or delete/replace them.*  
3. *Queue a re-indexing job. (over engineering vs a manual)*  
4. Generate new embeddings.  
5. Use the new embeddings for retrieval after re-indexing completes.

\\\\ should we store model changing history?

---

### **6\. Store embedding metadata** {#6.-store-embedding-metadata}

Every embedding should be traceable to the model that generated it.

The system should store:

embedding \_model\_name  
dimension  
modality  
created\_at

This is needed for debugging, migration, auditing, and future re-indexing.

---

## **2.2 Out of Scope for V1** {#2.2-out-of-scope-for-v1}

The following should not be included in V1 unless there is a strong business reason:

* Full embedding version management  
* Rollback between embedding versions  
* A/B testing embedding models  
* Simultaneous retrieval from multiple embedding models  
* Per-knowledge-base embedding model selection  
* Dedicated vector database migration  
* Hybrid search  
* Reranking  
* Audio/video embedding processing  
* Real-time re-indexing during active chat sessions

These can be considered future enhancements.

---

# **3\. Key Product Decision** {#3.-key-product-decision}

## **Group-Level Model Selection** {#group-level-model-selection}

The system will use **group-level embedding configuration**.

This means all knowledge bases inside a group will use the same embedding provider/model.

### **Why this is recommended** {#why-this-is-recommended}

Group-level selection is the right balance because:

* Platform-level selection is too restrictive.  
* Knowledge-base-level selection is too customizable.  
* Group-level selection supports different use cases across groups.  
* It keeps cost, debugging, and governance manageable.  
* It avoids confusing admins with too many model choices.

---

# **4\. Embedding Versioning Decision** {#4.-embedding-versioning-decision}

## **Recommendation: Do not build full active/inactive version management in V1** {#recommendation:-do-not-build-full-active/inactive-version-management-in-v1}

The system should store model metadata, but it does not need a full version-management feature yet.

### **V1 behavior** {#v1-behavior}

When the embedding model changes:

Old embeddings → replaced or marked stale  
New embeddings → generated and used

There should be one active embedding set per group.

### **Why not full versioning yet?** {#why-not-full-versioning-yet?}

Full versioning introduces extra complexity:

* Active/inactive model states  
* Rollback workflows  
* Retention policies  
* Duplicate storage  
* More complex retrieval logic  
* More admin UI decisions

For the current scale and maturity, this is not necessary.

### **What should still be stored** {#what-should-still-be-stored}

Even if old embeddings are replaced, the system should still know which model generated the current embeddings.

embedding\_model\_id  
provider  
model\_name  
dimension  
modality  
created\_at

This keeps the architecture future-ready without overcomplicating the product.

---

# **5\. Functional Requirements** {#5.-functional-requirements}

## **FR-1: Group Embedding Configuration** {#fr-1:-group-embedding-configuration}

The system shall allow each group to define one embedding provider and model.

Required fields:

group\_id  
embedding\_model\_id  
updated\_by  
updated\_at

The group embedding configuration should determine how all documents and chunks in that group are embedded.

---

## **FR-2: Embedding Model Registry** {#fr-2:-embedding-model-registry}

The system shall maintain a registry of supported embedding models.

Each model record shall include:

id  
provider  
model\_name  
dimension  
modality  
status  
created\_at  
updated\_at

Example:

| Provider | Model Name | Modality | Dimension | Status |
| ----- | ----- | ----- | ----- | ----- |
| OpenAI | text-embedding-3-small | text | 1536 | enabled |
| OpenAI | text-embedding-3-large | text | 3072 | enabled |
| Gemini | multimodal-embedding | text/image | provider-defined | future |
| Other | future-model | text/image | provider-defined | disabled |

The product UI should display models by provider and model name. Dimension should be treated as technical metadata, not as the main product concept.

---

## **FR-3: Document Storage** {#fr-3:-document-storage}

The system shall store uploaded source documents separately from embeddings.

Documents should include:

id  
group\_id  
knowledge\_base\_id  
file\_name  
file\_type  
source\_path  
content\_type  
upload\_status  
created\_by  
created\_at  
updated\_at

Supported content types:

text  
image  
audio  
video  
mixed

For V1, only text and image need processing support.

---

## **FR-4: Chunk Storage** {#fr-4:-chunk-storage}

The system shall split supported documents into retrievable chunks.

Chunks should include:

id  
document\_id  
chunk\_index  
content  
content\_type  
metadata  
created\_at

For text documents, chunks contain text.

For image documents, chunks may contain:

image reference  
image caption  
OCR text, if available  
metadata

This allows the system to retrieve image-related content without forcing all image processing into the first release.

---

## **FR-5: Embedding Storage** {#fr-5:-embedding-storage}

The system shall store embeddings separately from documents and chunks.

Each embedding should include:

id  
group\_id  
knowledge\_base\_id  
document\_id  
chunk\_id  
embedding\_model\_id  
vector  
modality  
status  
created\_at  
updated\_at

The embedding should always reference the model used to generate it.

---

## **FR-6: Re-indexing on Model Change** {#fr-6:-re-indexing-on-model-change}

When a group embedding model changes, the system shall trigger a re-indexing workflow.

The workflow should:

1. Identify all knowledge bases under the group.  
2. Identify all documents and chunks under those knowledge bases.  
3. Mark current embeddings as stale or delete them.  
4. Queue embedding generation jobs.  
5. Generate embeddings using the new group model.  
6. Mark indexing status as complete after successful processing.

During re-indexing, the group should show an indexing status such as:

Not Started  
In Progress  
Completed  
Failed  
Partially Failed

---

## **FR-7: Retrieval Uses Group Model** {#fr-7:-retrieval-uses-group-model}

During RAG retrieval, the system shall use the active embedding model configured for the group.

The query embedding model must match the document embedding model.

Example:

Group A uses OpenAI text-embedding-3-small

User query → embedded using OpenAI text-embedding-3-small  
Search → only against embeddings generated by OpenAI text-embedding-3-small

This prevents mismatched retrieval between different embedding spaces.

---

## **FR-8: Image Support** {#fr-8:-image-support}

The system shall support image-based knowledge base content in V1 at a basic level.

At minimum, the system should store:

image file  
image metadata  
image-derived text/caption, if available  
embedding reference

The system should be designed so that image embeddings can be generated using a multimodal embedding provider when enabled.

---

## **FR-9: Provider Abstraction** {#fr-9:-provider-abstraction}

The system shall provide an embedding provider abstraction layer.

The application should not call OpenAI, Gemini, or any provider directly from scattered parts of the codebase.

Instead, it should use a common interface:

generate\_embedding(input, model\_config)

The provider implementation should handle:

OpenAI text input  
Gemini text/image input  
future provider input

This reduces future changes when new providers are added.

---

# **6\. Non-Functional Requirements** {#6.-non-functional-requirements}

## **NFR-1: Maintainability** {#nfr-1:-maintainability}

Embedding provider logic should be modular.

Adding a new provider should not require rewriting the RAG pipeline.

---

## **NFR-2: Scalability** {#nfr-2:-scalability}

The system should support the current expected scale:

10–20 groups  
50–120 users per group  
Small-to-medium knowledge bases  
Text and image content

PGVector remains acceptable for this scale.

A dedicated vector database is not required in V1.

---

## **NFR-3: Reliability** {#nfr-3:-reliability}

Re-indexing jobs should support:

* Retry on failure  
* Failed document tracking  
* Partial completion status  
* Admin-visible indexing status

---

## **NFR-4: Traceability** {#nfr-4:-traceability}

The system should be able to answer:

* Which embedding model is used by this group?  
* Which model generated this embedding?  
* Which documents are indexed?  
* Which documents failed indexing?  
* Which groups need re-indexing after a model change?

---

## **NFR-5: Backward Compatibility** {#nfr-5:-backward-compatibility}

Existing text-based RAG should continue to work.

The migration should not break existing knowledge bases.

Existing embeddings can either be migrated into the new structure or regenerated using the configured group model.

---

# **7\. Recommended Data Model** {#7.-recommended-data-model}

## **7.1** {#7.1}

## **`embedding_models`** {#embedding_models}

Stores supported embedding models.

embedding\_models  
\- id  
\- provider  
\- model\_name  
\- dimension  
\- modality  
\- status  
\- created\_at  
\- updated\_at

Example statuses:

enabled  
disabled  
deprecated  
---

## **7.2** {#7.2}

## **`group_embedding_settings`** {#group_embedding_settings}

Stores group-level embedding configuration.

group\_embedding\_settings  
\- id  
\- group\_id  
\- embedding\_model\_id  
\- updated\_by  
\- updated\_at

Each group should have one active embedding setting.

---

## **7.3** {#7.3}

## **`documents`** {#documents}

Stores uploaded knowledge base documents.

documents  
\- id  
\- group\_id  
\- knowledge\_base\_id  
\- file\_name  
\- file\_type  
\- content\_type  
\- source\_path  
\- upload\_status  
\- created\_by  
\- created\_at  
\- updated\_at  
---

## **7.4** {#7.4}

## **`chunks`** {#chunks}

Stores searchable units derived from documents.

chunks  
\- id  
\- document\_id  
\- chunk\_index  
\- content  
\- content\_type  
\- metadata  
\- created\_at  
---

## **7.5** {#7.5}

## **`embeddings`** {#embeddings}

Stores vectors and model references.

embeddings  
\- id  
\- group\_id  
\- knowledge\_base\_id  
\- document\_id  
\- chunk\_id  
\- embedding\_model\_id  
\- vector  
\- modality  
\- status  
\- created\_at  
\- updated\_at

Possible statuses:

active  
stale  
failed  
processing

For V1, the product does not need to expose active/inactive model versions, but the backend can still use simple embedding statuses for operational tracking.

---

## **7.6** {#7.6}

## **`embedding_jobs`** {#embedding_jobs}

Tracks indexing and re-indexing jobs.

embedding\_jobs  
\- id  
\- group\_id  
\- knowledge\_base\_id  
\- embedding\_model\_id  
\- job\_type  
\- status  
\- started\_at  
\- completed\_at  
\- error\_message  
\- created\_by

Job types:

initial\_index  
reindex\_model\_change  
retry\_failed

Job statuses:

queued  
processing  
completed  
failed  
partially\_failed  
---

# **8\. PGVector Implementation Guidance** {#8.-pgvector-implementation-guidance}

The current issue is fixed-dimension vector storage.

PGVector works best when vectors in a given indexed column have the same dimension.

Therefore, the implementation should not assume that all embeddings live in one universal `vector(1536)` column.

## **Recommended approach** {#recommended-approach}

Use model-aware vector storage internally.

At the product layer, admins select:

Provider \+ Model

At the implementation layer, the system maps the model to the correct vector storage/index.

Example:

OpenAI text-embedding-3-small → vector dimension 1536  
OpenAI text-embedding-3-large → vector dimension 3072  
Gemini multimodal → provider-defined dimension

The product should not expose dimension-specific tables to users.

---

## **Practical Implementation Options** {#practical-implementation-options}

### **Option A: Separate vector tables by dimension** {#option-a:-separate-vector-tables-by-dimension}

Example:

embeddings\_1536  
embeddings\_3072  
embeddings\_768

Pros:

* Works well with PGVector  
* Easy to index  
* Clear dimension separation

Cons:

* More internal routing logic  
* New table may be needed for a new dimension

This is acceptable if handled internally.

---

### **Option B: Separate vector tables by model family** {#option-b:-separate-vector-tables-by-model-family}

Example:

openai\_text\_embeddings  
gemini\_multimodal\_embeddings

Pros:

* Easier to reason about provider-specific behavior  
* Useful when modalities differ

Cons:

* Less generic  
* Can become messy as providers increase

---

### **Recommendation** {#recommendation}

Use **model metadata at the product level** and **dimension-specific storage internally**.

The product should think in terms of:

embedding\_model\_id

The database/search implementation can decide which vector table/index to use.

This prevents product complexity while keeping PGVector performant.

---

# **9\. Re-indexing Workflow** {#9.-re-indexing-workflow}

## **Trigger** {#trigger}

Re-indexing is triggered when a group admin changes the group embedding model.

Example:

Group A changes from OpenAI text embedding to Gemini multimodal embedding

## **Workflow** {#workflow}

1\. Admin updates group embedding model  
2\. System marks existing embeddings as stale  
3\. System creates re-index job  
4\. Background worker processes documents/chunks  
5\. New embeddings are generated  
6\. Search uses new embeddings after completion  
7\. Failed chunks/documents are logged

## **Important Product Behavior** {#important-product-behavior}

During re-indexing, the UI should show:

Knowledge base is re-indexing. Search quality may be limited until indexing completes.

The system needs a clear decision:

### **Option 1: Continue using old embeddings until new indexing completes** {#option-1:-continue-using-old-embeddings-until-new-indexing-completes}

Pros:

* No downtime  
* Users can continue using RAG

Cons:

* Requires temporary support for old and new embeddings during migration

### **Option 2: Disable retrieval until re-indexing completes \[Recommended\]** {#option-2:-disable-retrieval-until-re-indexing-completes-[recommended]}

Pros:

* Simpler  
* Avoids inconsistent retrieval

Cons:

* Worse user experience

### **Recommendation** {#recommendation-1}

For V1, use **Option 2** if implementation time is limited.

For better user experience, use **Option 1**, but do not expose full version management in the UI.

\\\\ keeping old embeddings active until new indexing completes to avoid search downtime. It might take huge time if there are like 50 to 100 documents

### **Re-indexing Execution Strategy** {#re-indexing-execution-strategy}

Two implementation approaches are possible for executing re-indexing workloads.

#### **Method 1: Queue Workers (Redis-backed RQ Workers)** {#method-1:-queue-workers-(redis-backed-rq-workers)}

Re-indexing jobs can be executed using the Redis-backed RQ worker infrastructure. When an embedding model changes, the system creates a re-indexing job and pushes it into the Redis queue. Available workers consume the job, process document chunks, generate embeddings, and update job status in the database.

**Pros**

* Reuses infrastructure with minimal implementation effort  
* Lower operational complexity  
* Fast job startup with no pod creation overhead  
* Suitable for small to medium re-indexing workloads

**Cons**

* Large re-indexing jobs may monopolize shared workers  
* Can delay other background tasks such as document ingestion or PDF processing  
* Limited resource isolation since workers share CPU and memory  
* Horizontal scaling becomes harder for very large workloads

**Best suited for**

* Small knowledge bases  
* Lightweight or infrequent re-indexing  
* V1 implementation with limited infrastructure changes

#### **Method 2: Dedicated Kubernetes Jobs** {#method-2:-dedicated-kubernetes-jobs}

Re-indexing jobs can be executed using dedicated Kubernetes Jobs. When an embedding model changes, the API creates an embedding job record and launches a Kubernetes Job. The job runs a temporary worker pod that performs the re-indexing workflow and terminates after completion.

**Pros**

* Strong resource isolation with dedicated CPU and memory allocation  
* Better scalability for large re-indexing workloads  
* Prevents long-running jobs from affecting normal application workers  
* Easier to parallelize across multiple pods for large datasets

**Cons**

* Higher infrastructure and DevOps complexity  
* Slower startup due to pod scheduling overhead  
* Requires Kubernetes job orchestration and monitoring  
* More operational overhead compared to shared workers

**Best suited for**

* Large group-level re-indexing  
* Long-running batch embedding workloads  
* Future large-scale deployments

**Recommendation**  
For V1, Redis-backed RQ workers are sufficient for small-to-medium workloads and minimize implementation complexity. Dedicated Kubernetes Jobs can be introduced later if re-indexing workloads grow significantly and require better scalability or resource isolation.

---

# **10\. Admin Experience** {#10.-admin-experience}

## **Group Admin Settings** {#group-admin-settings}

The group admin should be able to view:

Current embedding provider  
Current embedding model  
Supported content types  
Indexing status  
Last indexed date

The admin may be able to change the embedding model if they have permission.

When changing model, show warning:

Changing the embedding model will require re-indexing all knowledge bases in this group. Retrieval may be unavailable or limited until indexing is complete.  
---

# **11\. Permissions** {#11.-permissions}

Embedding configuration should not be available to all users.

Recommended permissions:

| Role | Can View Embedding Model | Can Change Embedding Model |
| ----- | ----- | ----- |
| Super Admin | Yes | Yes |
| Admin | Yes | Yes, for assigned group |
| Co-Admin | Yes | Optional / No |
| Student/User | No | No |

For V1, I would restrict model changes to:

Super Admin  
Admin

Co-admins can view but not modify unless the broader RBAC model allows it.

---

# **12\. Search/RAG Behavior** {#12.-search/rag-behavior}

## **Query flow** {#query-flow}

User asks question  
↓  
System identifies user's group  
↓  
System reads group embedding model  
↓  
System embeds query using same model  
↓  
System searches matching embedding table/index  
↓  
System retrieves relevant chunks  
↓  
System sends chunks to LLM for answer generation

## **Important rule** {#important-rule}

The system must never compare a query embedding from one model with stored embeddings from another model.

For example, this should not happen:

Query embedded with Gemini  
Compared against OpenAI embeddings

That would produce unreliable results.

---

# **13\. Migration Plan** {#13.-migration-plan}

Might not need at all. If we say this functionality is available only in Production.

## **Phase 1: Create new schema** {#phase-1:-create-new-schema}

Add:

embedding\_models  
group\_embedding\_settings  
embedding\_jobs  
new embeddings structure  
---

## **Phase 2: Register current embedding model** {#phase-2:-register-current-embedding-model}

Create model record for the current provider/model.

Example:

Provider: OpenAI  
Model: text-embedding-3-small  
Dimension: 1536  
Modality: text  
Status: enabled  
---

## **Phase 3: Assign existing groups to current model** {#phase-3:-assign-existing-groups-to-current-model}

For all existing groups:

group\_embedding\_settings.embedding\_model\_id \= current\_model\_id  
---

## **Phase 4: Migrate or regenerate embeddings** {#phase-4:-migrate-or-regenerate-embeddings}

Choose one:

### **Migration** {#migration}

Move existing vectors into the new embedding structure and attach the correct model ID.

### **Regeneration** {#regeneration}

Re-embed all existing chunks using the current model.

Recommendation:

If existing data volume is small, regeneration is cleaner.

---

## **Phase 5: Add provider abstraction** {#phase-5:-add-provider-abstraction}

Refactor embedding generation logic so it uses:

EmbeddingService.generate(input, model\_config)

instead of hardcoded OpenAI calls.

---

## **Phase 6: Add image support** {#phase-6:-add-image-support}

Add processing for image uploads:

image storage  
image metadata  
image-derived text/caption  
image embedding, if supported by selected model  
---

# **14\. Development Scope** {#14.-development-scope}

## **Backend Scope** {#backend-scope}

### **Required** {#required}

* Add embedding model registry  
* Add group embedding settings  
* Add model-aware embedding generation  
* Add model-aware vector search  
* Add re-indexing job workflow  
* Add document/chunk/embedding metadata  
* Add image content type support  
* Add indexing status tracking

### **Optional for V1** {#optional-for-v1}

* Admin UI for changing embedding model  
* If no UI, initial configuration can be done by Super Admin or config table

---

## **Frontend Scope** {#frontend-scope}

### **Required** {#required-1}

In group settings/admin panel:

* Show current embedding provider/model  
* Show indexing status  
* Show warning before model change  
* Show re-indexing progress/status

### **Optional** {#optional}

* Allow admin to change model from UI  
* Show supported modalities  
* Show failed documents with retry option

---

## **Database Scope** {#database-scope}

Required schema changes:

embedding\_models  
group\_embedding\_settings  
embedding\_jobs  
updated documents/chunks/embeddings

PGVector indexing should be adjusted to support multiple dimensions internally.

---

## **Worker/Queue Scope** {#worker/queue-scope}

Required background jobs:

initial embedding generation  
re-index after model change  
retry failed embedding jobs  
---

# **15\. Acceptance Criteria** {#15.-acceptance-criteria}

## **AC-1: Existing RAG continues to work** {#ac-1:-existing-rag-continues-to-work}

Given an existing text knowledge base, when a user asks a question, the system retrieves relevant chunks and generates an answer using the current embedding model.

---

## **AC-2: Group has embedding configuration** {#ac-2:-group-has-embedding-configuration}

Given a group, the system can identify which embedding provider/model is assigned to that group.

---

## **AC-3: Query and document embeddings use same model** {#ac-3:-query-and-document-embeddings-use-same-model}

Given a group using Model A, both query embeddings and document embeddings are generated using Model A.

---

## **AC-4: Model change triggers re-indexing** {#ac-4:-model-change-triggers-re-indexing}

Given an admin changes the group embedding model, the system creates a re-indexing job for that group’s knowledge bases.

---

## **AC-5: Embedding metadata is stored** {#ac-5:-embedding-metadata-is-stored}

Given an embedding is generated, the system stores the model/provider/dimension metadata associated with that embedding.

---

## **AC-6: Image content can be stored** {#ac-6:-image-content-can-be-stored}

Given a supported image file is uploaded, the system stores the image and associated metadata under the correct knowledge base.

---

## **AC-7: Failed embedding jobs are trackable** {#ac-7:-failed-embedding-jobs-are-trackable}

Given an embedding job fails, the system records the failure status and error message.

---

# **16\. Future Scope** {#16.-future-scope}

The following can be added later:

## **V2** {#v2}

* Hybrid search  
* Reranking  
* Better image retrieval  
* OCR and captioning pipeline  
* Embedding cost tracking  
* Admin retry for failed documents

## **V3** {#v3}

* Audio embeddings  
* Video embeddings  
* Cross-modal retrieval  
* Full embedding versioning  
* Rollback between embedding models  
* A/B testing retrieval quality  
* Dedicated vector database evaluation

---

# **17\. Final Recommended V1 Scope** {#17.-final-recommended-v1-scope}

For V1, I would scope it like this:

Build a group-level, provider-aware embedding architecture that supports variable embedding dimensions, text and image content, and re-indexing when the group embedding model changes, while continuing to use PGVector as the vector backend.

## **V1 should include** {#v1-should-include}

* Group-level embedding model selection  
* Embedding model registry  
* Provider abstraction layer  
* Text embedding support  
* Basic image content support  
* Model-aware query embedding  
* Model-aware vector retrieval  
* Re-indexing workflow  
* Embedding metadata tracking  
* Indexing status tracking

## **V1 should not include** {#v1-should-not-include}

* Full embedding version management  
* Rollback  
* Multiple active embedding models  
* Per-KB model selection  
* Dedicated vector DB  
* Audio/video processing  
* Hybrid search  
* Reranking

This keeps the scope practical while still solving the real architectural problem: the system should no longer be locked to one provider, one model, one dimension, and text-only RAG.

