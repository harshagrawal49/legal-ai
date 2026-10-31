package com.nyaya.legal.ui.markdown

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The chat renders LLM Markdown; these pin down what the parser does with typical replies. */
class MarkdownParserTest {

    private val reply = """
        Short answer: the amounts **differ**.

        ### What each document says
        | Document | Advance | Page |
        |---|---|---|
        | Agreement | Rs. 5,00,000/- | [[D:7f3c-aa:p1]] |
        | Receipt | Rs. 5,50,000/- | [[D:9b1e-bb:p1]] |

        - Survey number in advance_receipt.pdf is **123/A**
          and this line continues the item
          - nested point
        1. First step
        2. Second step
        - [ ] Get the original receipt
        > The notice says the plot was sold again.
        ---
        ```
        code here
        ```
        Trailing paragraph.
    """.trimIndent()

    @Test fun parsesATypicalReply() {
        val b = parseMarkdown(reply)
        assertTrue(b[0] is MdBlock.Paragraph)
        assertEquals(3, (b[1] as MdBlock.Heading).level)
        val table = b[2] as MdBlock.Table
        assertEquals(listOf("Document", "Advance", "Page"), table.header)
        assertEquals("[[D:9b1e-bb:p1]]", table.rows[1][2])
        val item = b[3] as MdBlock.ListItem
        assertEquals("•", item.marker)
        assertTrue(item.text.endsWith("and this line continues the item"))
        assertEquals(1, (b[4] as MdBlock.ListItem).depth)
        assertEquals("1.", (b[5] as MdBlock.ListItem).marker)
        assertEquals("☐", (b[7] as MdBlock.ListItem).marker)
        assertTrue(b[8] is MdBlock.Quote)
        assertEquals(MdBlock.Rule, b[9])
        assertEquals("code here", (b[10] as MdBlock.Code).text)
        assertTrue(b[11] is MdBlock.Paragraph)
    }

    @Test fun inlineLeavesFilenamesAndCitationsAlone() {
        val text = "See advance_receipt.pdf and [[D:7f3c:p1]] **bold [[J:2019_SC_12]]** *it* `c` [Kanoon](https://x.org/a)"
        assertEquals(
            listOf("**bold [[J:2019_SC_12]]**", "*it*", "`c`", "[Kanoon](https://x.org/a)"),
            INLINE.findAll(text).map { it.value }.toList(),
        )
        assertTrue(INLINE.findAll("the amount is **Rs 5,5").none()) // half-streamed
        assertTrue(INLINE.findAll("5 * 3 = 15").none())
    }

    @Test fun tablesAreTolerant() {
        assertTrue(parseMarkdown("| A | B |")[0] is MdBlock.Paragraph) // separator not streamed yet
        assertEquals(listOf("1", "2", ""), (parseMarkdown("|a|b|c|\n|-|-|-|\n|1|2|")[0] as MdBlock.Table).rows[0])
        assertEquals(listOf("a | b", "c"), splitTableRow("| a \\| b | c |"))
    }

    @Test fun keepsHindiAndEmptyInput() {
        assertTrue((parseMarkdown("- रसीद में **रुपये ५,५०,०००** लिखा है")[0] as MdBlock.ListItem).text.contains("५,५०,०००"))
        assertTrue(parseMarkdown("").isEmpty())
    }
}
