package com.nyaya.legal.data

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody

private const val MAX_UPLOAD_BYTES = 10 * 1024 * 1024 // same limit as the backend

/** MIME type for the system file picker. Only PDFs are supported by the backend. */
const val PDF_MIME = "application/pdf"

/** Read a picked file and upload it to the case. Errors are IllegalStateException (shown as-is) or HTTP errors. */
suspend fun uploadPdf(resolver: ContentResolver, caseId: String, uri: Uri): DocumentDetail {
    val name = displayName(resolver, uri)
    val bytes = withContext(Dispatchers.IO) {
        resolver.openInputStream(uri)?.use { it.readBytes() } ?: throw IllegalStateException("Could not open the file.")
    }
    check(bytes.size <= MAX_UPLOAD_BYTES) { "The file is larger than 10 MB." }
    val part = MultipartBody.Part.createFormData("file", name, bytes.toRequestBody(PDF_MIME.toMediaType()))
    return Api.service.uploadDocument(caseId, part)
}

private fun displayName(resolver: ContentResolver, uri: Uri): String =
    resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
        if (c.moveToFirst()) c.getString(0) else null
    } ?: "document.pdf"
