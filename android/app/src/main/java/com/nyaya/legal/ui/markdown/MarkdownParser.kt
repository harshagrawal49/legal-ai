package com.nyaya.legal.ui.markdown

/**
 * A small Markdown block parser for LLM replies, tuned for a phone screen. Pure Kotlin (no Android
 * types) so it can be unit-tested on the JVM.
 *
 * Supported: headings, paragraphs, bullet / numbered / task lists (nested by indentation), block
 * quotes, horizontal rules, fenced code, and pipe tables. Inline styling (bold, italic, code) is
 * handled when rendering ([appendInline]). Anything unrecognised is kept as plain text, so a
 * half-streamed reply never loses words.
 */
sealed interface MdBlock {
    data class Heading(val level: Int, val text: String) : MdBlock
    data class Paragraph(val text: String) : MdBlock
    /** [marker] is what to draw: "•", "◦", "1.", "☐" or "☑". [depth] starts at 0. */
    data class ListItem(val depth: Int, val marker: String, val text: String) : MdBlock
    data class Quote(val text: String) : MdBlock
    data object Rule : MdBlock
    data class Code(val text: String) : MdBlock
    data class Table(val header: List<String>, val rows: List<List<String>>) : MdBlock
}

private val HEADING = Regex("""^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$""")
private val RULE = Regex("""^\s{0,3}([-*_])(\s*\1){2,}\s*$""")
private val LIST_ITEM = Regex("""^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$""")
private val TASK = Regex("""^\[([ xX])]\s+(.*)$""")
private val QUOTE = Regex("""^\s{0,3}>\s?(.*)$""")
private val FENCE = Regex("""^\s{0,3}(```|~~~)""")
private val TABLE_SEPARATOR = Regex("""^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$""")

/** Leading-space width, with a tab counted as 4 spaces. */
private fun indentOf(line: String): Int {
    var n = 0
    for (c in line) {
        when (c) {
            ' ' -> n += 1
            '\t' -> n += 4
            else -> return n
        }
    }
    return n
}

/** "| a | b |" → ["a", "b"]. Escaped pipes (\|) stay inside a cell. */
fun splitTableRow(line: String): List<String> {
    var s = line.trim()
    if (s.startsWith("|")) s = s.substring(1)
    if (s.endsWith("|") && !s.endsWith("\\|")) s = s.dropLast(1)
    val cells = mutableListOf<String>()
    val cur = StringBuilder()
    var i = 0
    while (i < s.length) {
        val c = s[i]
        if (c == '\\' && i + 1 < s.length && s[i + 1] == '|') {
            cur.append('|'); i += 2; continue
        }
        if (c == '|') {
            cells.add(cur.toString().trim()); cur.clear()
        } else {
            cur.append(c)
        }
        i++
    }
    cells.add(cur.toString().trim())
    return cells
}

private fun isTableRow(line: String) = line.contains('|') && line.isNotBlank()

fun parseMarkdown(text: String): List<MdBlock> {
    val lines = text.replace("\r\n", "\n").split('\n')
    val out = mutableListOf<MdBlock>()
    val para = mutableListOf<String>()

    fun flushPara() {
        if (para.isNotEmpty()) {
            out.add(MdBlock.Paragraph(para.joinToString("\n")))
            para.clear()
        }
    }

    var i = 0
    // Indentation of the list's first level, so a list indented by 2 or 3 spaces still starts at depth 0.
    var listBase = -1
    while (i < lines.size) {
        val line = lines[i]

        // Fenced code
        if (FENCE.containsMatchIn(line)) {
            flushPara()
            val body = mutableListOf<String>()
            i++
            while (i < lines.size && !FENCE.containsMatchIn(lines[i])) {
                body.add(lines[i]); i++
            }
            out.add(MdBlock.Code(body.joinToString("\n")))
            i++ // closing fence (or end of a half-streamed reply)
            continue
        }

        if (line.isBlank()) {
            flushPara(); listBase = -1; i++; continue
        }

        // Table: a row with pipes followed by a separator row
        if (isTableRow(line) && i + 1 < lines.size && TABLE_SEPARATOR.matches(lines[i + 1])) {
            flushPara()
            val header = splitTableRow(line)
            val rows = mutableListOf<List<String>>()
            i += 2
            while (i < lines.size && isTableRow(lines[i]) && !TABLE_SEPARATOR.matches(lines[i])) {
                val cells = splitTableRow(lines[i])
                // Pad or trim so every row lines up with the header.
                rows.add(List(header.size) { c -> cells.getOrElse(c) { "" } })
                i++
            }
            out.add(MdBlock.Table(header, rows))
            continue
        }

        val heading = HEADING.matchEntire(line)
        if (heading != null) {
            flushPara()
            out.add(MdBlock.Heading(heading.groupValues[1].length, heading.groupValues[2]))
            i++
            continue
        }

        if (RULE.matches(line)) {
            flushPara(); out.add(MdBlock.Rule); i++; continue
        }

        val item = LIST_ITEM.matchEntire(line)
        if (item != null) {
            val m = item
            flushPara()
            val indent = indentOf(m.groupValues[1])
            if (listBase < 0 || indent < listBase) listBase = indent
            val depth = ((indent - listBase) / 2).coerceIn(0, 3)
            val rawMarker = m.groupValues[2]
            var body = m.groupValues[3]
            var marker = when {
                rawMarker.first().isDigit() -> rawMarker.dropLast(1) + "."
                depth == 0 -> "•"
                else -> "◦"
            }
            TASK.matchEntire(body)?.let { t ->
                marker = if (t.groupValues[1].isBlank()) "☐" else "☑"
                body = t.groupValues[2]
            }
            // Continuation lines: indented further than the marker and not a new block.
            i++
            val cont = StringBuilder(body)
            while (i < lines.size) {
                val next = lines[i]
                if (next.isBlank() || LIST_ITEM.matches(next) || HEADING.matches(next) || QUOTE.matches(next) ||
                    FENCE.containsMatchIn(next) || (isTableRow(next) && i + 1 < lines.size && TABLE_SEPARATOR.matches(lines[i + 1]))
                ) break
                if (indentOf(next) <= indent) break
                cont.append(' ').append(next.trim())
                i++
            }
            out.add(MdBlock.ListItem(depth, marker, cont.toString()))
            continue
        }

        val quote = QUOTE.matchEntire(line)
        if (quote != null) {
            flushPara()
            val body = mutableListOf(quote.groupValues[1])
            i++
            while (i < lines.size) {
                val q = QUOTE.matchEntire(lines[i]) ?: break
                body.add(q.groupValues[1]); i++
            }
            out.add(MdBlock.Quote(body.joinToString("\n").trim()))
            continue
        }

        // A non-indented line right after a list ends the list.
        listBase = -1
        para.add(line.trim())
        i++
    }
    flushPara()
    return out
}

/**
 * Inline tokens, in the order they're tried. Underscore emphasis needs a non-word character on both
 * sides so filenames like advance_receipt.pdf are left alone. Citation markers like [[D:…:p1]] never
 * match the link pattern because a link needs "](" right after the label.
 */
internal val INLINE = Regex(
    """\*\*(.+?)\*\*""" +                                  // 1 bold
        """|__(.+?)__""" +                                 // 2 bold
        """|(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])""" + // 3 italic
        """|(?<![\w])_(?![\s_])(.+?)(?<![\s_])_(?![\w])""" +   // 4 italic
        """|`([^`\n]+)`""" +                               // 5 code
        """|(?<!\[)\[([^\[\]\n]+)]\((?:https?://|mailto:)[^)\s]+\)""", // 6 link label (URL dropped)
)
