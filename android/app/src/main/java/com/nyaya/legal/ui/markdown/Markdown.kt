package com.nyaya.legal.ui.markdown

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp

/** How plain (un-styled) text is appended. Chat uses this to turn citation markers into links. */
typealias PlainAppender = AnnotatedString.Builder.(String) -> Unit

private val appendPlain: PlainAppender = { append(it) }

/** Appends [text] with **bold**, *italic*, `code` and [label](url) handled; everything else goes through [plain]. */
fun AnnotatedString.Builder.appendInline(text: String, plain: PlainAppender = appendPlain) {
    var last = 0
    for (m in INLINE.findAll(text)) {
        if (m.range.first > last) plain(text.substring(last, m.range.first))
        val g = m.groupValues
        when {
            g[1].isNotEmpty() -> withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { appendInline(g[1], plain) }
            g[2].isNotEmpty() -> withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { appendInline(g[2], plain) }
            g[3].isNotEmpty() -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { appendInline(g[3], plain) }
            g[4].isNotEmpty() -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { appendInline(g[4], plain) }
            g[5].isNotEmpty() -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = Color(0x1F808080))) { append(g[5]) }
            g[6].isNotEmpty() -> appendInline(g[6], plain)
            else -> plain(m.value)
        }
        last = m.range.last + 1
    }
    if (last < text.length) plain(text.substring(last))
}

fun markdownInline(text: String, plain: PlainAppender = appendPlain): AnnotatedString =
    buildAnnotatedString { appendInline(text, plain) }

/**
 * Renders LLM text for a phone: real bullets with hanging indents, headings, and tables turned into
 * one small card per row (a 4-column table can't be read at 360 dp wide).
 */
@Composable
fun MarkdownText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.bodyMedium,
    color: Color = Color.Unspecified,
    plain: PlainAppender = appendPlain,
) {
    val blocks = remember(text) { parseMarkdown(text) }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        blocks.forEach { block ->
            when (block) {
                is MdBlock.Heading -> Text(
                    markdownInline(block.text, plain),
                    style = if (block.level <= 2) MaterialTheme.typography.titleMedium else MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = color,
                    modifier = Modifier.padding(top = 4.dp),
                )
                is MdBlock.Paragraph -> Text(markdownInline(block.text, plain), style = style, color = color)
                is MdBlock.ListItem -> Bullet(block.marker, block.depth, style, color) {
                    Text(markdownInline(block.text, plain), style = style, color = color)
                }
                is MdBlock.Quote -> QuoteBlock { Text(markdownInline(block.text, plain), style = style, color = color, fontStyle = FontStyle.Italic) }
                MdBlock.Rule -> HorizontalDivider(Modifier.padding(vertical = 4.dp))
                is MdBlock.Code -> Surface(
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    // Code is the one thing that may scroll sideways; wrapping would change its meaning.
                    Text(
                        block.text,
                        style = style.copy(fontFamily = FontFamily.Monospace),
                        modifier = Modifier.horizontalScroll(rememberScrollState()).padding(10.dp),
                    )
                }
                is MdBlock.Table -> TableAsCards(block, style, color, plain)
            }
        }
    }
}

/** A bullet with a hanging indent: wrapped lines line up with the text, not under the marker. */
@Composable
fun Bullet(
    marker: String = "•",
    depth: Int = 0,
    style: TextStyle = MaterialTheme.typography.bodyMedium,
    color: Color = Color.Unspecified,
    content: @Composable () -> Unit,
) {
    Row(Modifier.fillMaxWidth().padding(start = (depth * 16).dp)) {
        Text(
            marker,
            style = style,
            color = color,
            modifier = Modifier.widthIn(min = if (marker.length > 1) 26.dp else 16.dp).padding(end = 6.dp),
        )
        Box(Modifier.weight(1f)) { content() }
    }
}

/** Shorthand for a one-line (or wrapping) bullet of LLM text. */
@Composable
fun BulletText(
    text: String,
    marker: String = "•",
    style: TextStyle = MaterialTheme.typography.bodyMedium,
    color: Color = Color.Unspecified,
) {
    Bullet(marker, 0, style, color) { Text(markdownInline(text), style = style, color = color) }
}

@Composable
private fun QuoteBlock(content: @Composable () -> Unit) {
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Box(Modifier.width(3.dp).fillMaxHeight().background(MaterialTheme.colorScheme.outline, RoundedCornerShape(2.dp)))
        Box(Modifier.weight(1f).padding(start = 10.dp)) { content() }
    }
}

/**
 * Each row becomes a card: the first cell is the card's title, the other cells are "Header" over
 * value. Two-column key/value tables read naturally this way too.
 */
@Composable
private fun TableAsCards(table: MdBlock.Table, style: TextStyle, color: Color, plain: PlainAppender) {
    val header = table.header
    // A table with no data rows is just its header: show it as a line of text.
    if (table.rows.isEmpty()) {
        Text(markdownInline(header.filter { it.isNotBlank() }.joinToString(" · "), plain), style = style, color = color)
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        table.rows.forEach { row ->
            Surface(
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    row.forEachIndexed { c, cell ->
                        if (cell.isBlank()) return@forEachIndexed
                        if (c == 0) {
                            Text(markdownInline(cell, plain), style = style, color = color, fontWeight = FontWeight.SemiBold)
                        } else {
                            val label = header.getOrNull(c).orEmpty()
                            if (label.isNotBlank()) {
                                Text(
                                    markdownInline(label),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Text(markdownInline(cell, plain), style = style, color = color)
                        }
                    }
                }
            }
        }
    }
}
