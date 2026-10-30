package com.nyaya.legal.data

import com.nyaya.legal.BuildConfig
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import okhttp3.MultipartBody
import retrofit2.HttpException
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import java.util.concurrent.TimeUnit

interface NyayaService {
    @GET("cases") suspend fun listCases(): List<CaseSummary>
    @POST("cases") suspend fun createCase(@Body body: NewCaseRequest): CaseDetail
    @GET("cases/{id}") suspend fun getCase(@Path("id") id: String): CaseDetail
    @POST("cases/{id}/intake") suspend fun answer(@Path("id") id: String, @Body body: IntakeAnswerRequest): CaseDetail
    @POST("cases/{id}/search") suspend fun search(@Path("id") id: String): List<CaseResult>
    @GET("cases/{id}/results") suspend fun results(@Path("id") id: String): List<CaseResult>
    @GET("cases/{id}/chat") suspend fun chatHistory(@Path("id") id: String): List<ChatMessage>
    @GET("judgments/{id}") suspend fun judgment(@Path("id") id: String): JudgmentDetail

    @Multipart @POST("cases/{id}/documents")
    suspend fun uploadDocument(@Path("id") id: String, @Part file: MultipartBody.Part): DocumentDetail
    @GET("cases/{id}/documents") suspend fun documents(@Path("id") id: String): List<DocumentSummary>
    @GET("cases/{id}/documents/{docId}")
    suspend fun document(@Path("id") id: String, @Path("docId") docId: String): DocumentDetail
    @POST("cases/{id}/documents/{docId}/extract")
    suspend fun retryExtraction(@Path("id") id: String, @Path("docId") docId: String): DocumentDetail
    @DELETE("cases/{id}/documents/{docId}")
    suspend fun deleteDocument(@Path("id") id: String, @Path("docId") docId: String): retrofit2.Response<Unit>
    @GET("cases/{id}/evidence") suspend fun evidence(@Path("id") id: String): Evidence
    @POST("cases/{id}/brief") suspend fun brief(@Path("id") id: String): Brief
}

/** Events of a streamed chat reply. */
sealed interface ChatEvent {
    data class Text(val delta: String) : ChatEvent
    data class Tool(val name: String) : ChatEvent
    /** `unverified` holds judgment ids and "<document id>:p<N>" references the backend could not verify. */
    data class Done(val citedJudgments: List<String>, val unverified: Set<String> = emptySet()) : ChatEvent
    data class Error(val message: String) : ChatEvent
}

object Api {
    val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    // LLM calls (intake, search analysis) can take a while, so timeouts are generous.
    private val http = OkHttpClient.Builder()
        .readTimeout(3, TimeUnit.MINUTES)
        .addInterceptor { chain ->
            // TODO(auth): send the Supabase access token instead of a fixed user id.
            chain.proceed(chain.request().newBuilder().header("X-User-Id", "dev-user").build())
        }
        .addInterceptor(HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC })
        .build()

    val service: NyayaService = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(http)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(NyayaService::class.java)

    /** POST a chat message and stream back the reply as server-sent events. */
    fun chat(caseId: String, message: String): Flow<ChatEvent> = callbackFlow {
        val body = json.encodeToString(ChatRequest.serializer(), ChatRequest(message))
            .toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url(BuildConfig.API_BASE_URL + "cases/$caseId/chat")
            .post(body)
            .build()

        val listener = object : EventSourceListener() {
            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                val obj = json.parseToJsonElement(data).jsonObject
                when (type) {
                    "text" -> trySend(ChatEvent.Text(obj.string("delta")))
                    "tool" -> trySend(ChatEvent.Tool(obj.string("name")))
                    "done" -> {
                        fun strings(key: String) = obj[key]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty()
                        val unverified = strings("unverified_citations") + strings("unverified_document_citations")
                        trySend(ChatEvent.Done(strings("cited_judgments"), unverified.toSet()))
                        close()
                    }
                    "error" -> {
                        trySend(ChatEvent.Error(obj.string("message")))
                        close()
                    }
                }
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                trySend(ChatEvent.Error(t?.message ?: "Connection failed (${response?.code})"))
                close()
            }

            override fun onClosed(eventSource: EventSource) {
                close()
            }
        }
        val source = EventSources.createFactory(http.newBuilder().readTimeout(5, TimeUnit.MINUTES).build())
            .newEventSource(request, listener)
        awaitClose { source.cancel() }
    }

    /** The backend's `detail` message for HTTP errors (e.g. "Only PDF files are supported."), else a generic one. */
    fun errorMessage(t: Throwable): String {
        if (t is HttpException) {
            val detail = runCatching {
                json.parseToJsonElement(t.response()?.errorBody()?.string().orEmpty()).jsonObject["detail"]?.jsonPrimitive?.content
            }.getOrNull()
            return detail ?: "The server returned an error (${t.code()})."
        }
        if (t is IllegalStateException) return t.message ?: "Something went wrong."  // checks made in the app
        return "Could not reach the server. Check your connection and try again."
    }

    private fun JsonObject.string(key: String) = this[key]?.jsonPrimitive?.content.orEmpty()
}
