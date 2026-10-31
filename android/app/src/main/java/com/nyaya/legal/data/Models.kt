package com.nyaya.legal.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// Mirrors backend/app/schemas.py and backend/app/llm/schemas.py.

@Serializable
data class Party(val name: String = "", val role: String = "")

@Serializable
data class Event(val date: String? = null, val description: String = "")

@Serializable
data class Amount(val description: String = "", val value: String = "")

@Serializable
data class FactSheet(
    val summary: String = "",
    val parties: List<Party> = emptyList(),
    val events: List<Event> = emptyList(),
    val amounts: List<Amount> = emptyList(),
    val documents: List<String> = emptyList(),
    @SerialName("actions_taken") val actionsTaken: List<String> = emptyList(),
    @SerialName("relief_sought") val reliefSought: String? = null,
    val location: String? = null,
    val issues: List<String> = emptyList(),
    @SerialName("legal_areas") val legalAreas: List<String> = emptyList(),
    @SerialName("search_queries") val searchQueries: List<String> = emptyList(),
    @SerialName("missing_info") val missingInfo: List<String> = emptyList(),
)

@Serializable
data class CaseSummary(
    val id: String,
    val title: String,
    val status: String,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class CaseDetail(
    val id: String,
    val title: String,
    val status: String,
    @SerialName("updated_at") val updatedAt: String,
    @SerialName("fact_sheet") val factSheet: FactSheet = FactSheet(),
    @SerialName("pending_questions") val pendingQuestions: List<String> = emptyList(),
    val results: List<CaseResult> = emptyList(),
)

@Serializable
data class JudgmentBrief(
    val id: String,
    val title: String,
    val court: String,
    @SerialName("decision_date") val decisionDate: String? = null,
    val citation: String? = null,
    @SerialName("neutral_citation") val neutralCitation: String? = null,
    val disposal: String? = null,
    @SerialName("source_url") val sourceUrl: String,
    val summary: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class CaseResult(
    val rank: Int,
    val relevance: Int,
    val stance: String, // supports | opposes | mixed
    val explanation: String,
    val similarities: List<String> = emptyList(),
    val differences: List<String> = emptyList(),
    @SerialName("key_paragraphs") val keyParagraphs: List<Int> = emptyList(),
    val judgment: JudgmentBrief,
)

@Serializable
data class Paragraph(@SerialName("para_no") val paraNo: Int, val text: String)

@Serializable
data class JudgmentDetail(
    val id: String,
    val title: String,
    val court: String,
    @SerialName("decision_date") val decisionDate: String? = null,
    val citation: String? = null,
    @SerialName("neutral_citation") val neutralCitation: String? = null,
    val disposal: String? = null,
    @SerialName("source_url") val sourceUrl: String,
    val summary: JsonObject = JsonObject(emptyMap()),
    val petitioner: String? = null,
    val respondent: String? = null,
    val judges: String? = null,
    val paragraphs: List<Paragraph> = emptyList(),
)

@Serializable
data class ChatMessage(
    val id: Int,
    val role: String,
    @SerialName("display_text") val displayText: String,
)

// Request bodies
@Serializable
data class NewCaseRequest(val description: String)

@Serializable
data class IntakeAnswerRequest(val text: String)

@Serializable
data class ChatRequest(val message: String)

// ---------- Uploaded documents, evidence pack and brief ----------

@Serializable
data class DocumentSummary(
    val id: String,
    val filename: String,
    val status: String, // processed | text_only | failed
    val error: String? = null,
    @SerialName("document_type") val documentType: String? = null,
    @SerialName("page_count") val pageCount: Int = 0,
    @SerialName("ocr_pages") val ocrPages: Int = 0,
)

@Serializable
data class DocumentDetail(
    val id: String,
    val filename: String,
    val status: String,
    val error: String? = null,
    @SerialName("document_type") val documentType: String? = null,
    @SerialName("page_count") val pageCount: Int = 0,
    @SerialName("ocr_pages") val ocrPages: Int = 0,
    val pages: List<String> = emptyList(),
    /** Per page: {"source": "text" | "ocr" | "ocr_unreadable" | ..., "engine", "confidence"}. */
    @SerialName("page_info") val pageInfo: List<JsonObject> = emptyList(),
    val facts: JsonObject = JsonObject(emptyMap()), // backend/app/llm/schemas.py: DocumentFacts
)

@Serializable
data class SourceRef(
    @SerialName("document_id") val documentId: String,
    val filename: String,
    val page: Int? = null,
    val excerpt: String? = null,
    val verified: Boolean = false,
    @SerialName("from_ocr") val fromOcr: Boolean = false,
    val value: String? = null,
)

@Serializable
data class TimelineItem(
    val date: String? = null,
    @SerialName("date_as_written") val dateAsWritten: String? = null,
    val kind: String,
    val description: String,
    val source: SourceRef,
)

@Serializable
data class Flag(val kind: String, val message: String, val sources: List<SourceRef> = emptyList())

@Serializable
data class Evidence(val timeline: List<TimelineItem> = emptyList(), val flags: List<Flag> = emptyList())

@Serializable
data class SupportedFact(val category: String, val text: String, val source: SourceRef)

@Serializable
data class LegalSource(
    @SerialName("judgment_id") val judgmentId: String,
    val title: String,
    val court: String,
    @SerialName("decision_date") val decisionDate: String? = null,
    val citation: String? = null,
    @SerialName("why_it_may_matter") val whyItMayMatter: String,
    @SerialName("key_paragraphs") val keyParagraphs: List<Int> = emptyList(),
)

@Serializable
data class Brief(
    val disclaimer: String,
    @SerialName("user_summary") val userSummary: String? = null,
    val documents: List<BriefDocument> = emptyList(),
    val chronology: List<TimelineItem> = emptyList(),
    @SerialName("document_supported_facts") val supportedFacts: List<SupportedFact> = emptyList(),
    @SerialName("user_account_not_verified") val userAccount: List<String> = emptyList(),
    @SerialName("gaps_and_inconsistencies") val gaps: List<Flag> = emptyList(),
    @SerialName("legal_sources") val legalSources: List<LegalSource> = emptyList(),
    @SerialName("advocate_questions") val advocateQuestions: List<String> = emptyList(),
    val checklist: List<String> = emptyList(),
    @SerialName("suggestions_ai_generated") val suggestionsAiGenerated: Boolean = false,
)

@Serializable
data class BriefDocument(
    @SerialName("document_id") val documentId: String,
    val filename: String,
    val status: String,
    @SerialName("document_type") val documentType: String? = null,
    @SerialName("page_count") val pageCount: Int = 0,
    val error: String? = null,
    @SerialName("ocr_pages") val ocrPages: Int = 0,
    @SerialName("ocr_confidence") val ocrConfidence: Double? = null,
)
