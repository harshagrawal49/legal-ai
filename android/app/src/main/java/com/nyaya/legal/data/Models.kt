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
