/*
 * RecoverX Native C High-Speed Signature Scanner
 * Scans raw disk chunks for candidate signature prefixes in a single pass.
 */
#include <stdint.h>
#include <stddef.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

EXPORT size_t scan_chunk_prefixes(
    const uint8_t* buf,
    size_t buf_len,
    int32_t* out_offsets,
    size_t max_results
) {
    if (!buf || buf_len < 8 || !out_offsets || max_results == 0) {
        return 0;
    }
    size_t count = 0;
    size_t limit = buf_len - 8;
    for (size_t i = 0; i <= limit; ++i) {
        uint8_t b0 = buf[i];
        int match = 0;
        switch (b0) {
            case 0xFF:
                /* JPEG: FF D8 FF or MP3 sync: FF FB / FF F3 */
                if (buf[i+1] == 0xD8 && buf[i+2] == 0xFF) match = 1;
                break;
            case 0x89:
                /* PNG: 89 50 4E 47 0D 0A 1A 0A */
                if (buf[i+1] == 0x50 && buf[i+2] == 0x4E && buf[i+3] == 0x47) match = 1;
                break;
            case 0x47:
                /* GIF: GIF87a / GIF89a */
                if (buf[i+1] == 0x49 && buf[i+2] == 0x46 && buf[i+3] == 0x38) match = 1;
                break;
            case 0x42:
                /* BMP: BM */
                if (buf[i+1] == 0x4D && (i % 512 == 0)) match = 1;
                break;
            case 0x49:
                /* TIFF LE: II*\0 or ID3: ID3 */
                if ((buf[i+1] == 0x49 && buf[i+2] == 0x2A && buf[i+3] == 0x00) ||
                    (buf[i+1] == 0x44 && buf[i+2] == 0x33)) match = 1;
                break;
            case 0x4D:
                /* TIFF BE: MM\0* */
                if (buf[i+1] == 0x4D && buf[i+2] == 0x00 && buf[i+3] == 0x2A) match = 1;
                break;
            case 0x52:
                /* RIFF (WebP, WAV, AVI) or Rar! */
                if ((buf[i+1] == 0x49 && buf[i+2] == 0x46 && buf[i+3] == 0x46) ||
                    (buf[i+1] == 0x61 && buf[i+2] == 0x72 && buf[i+3] == 0x21)) match = 1;
                break;
            case 0x25:
                /* PDF: %PDF- */
                if (buf[i+1] == 0x50 && buf[i+2] == 0x44 && buf[i+3] == 0x46 && buf[i+4] == 0x2D) match = 1;
                break;
            case 0x50:
                /* ZIP / DOCX / XLSX / PPTX: PK\x03\x04 */
                if (buf[i+1] == 0x4B && buf[i+2] == 0x03 && buf[i+3] == 0x04) match = 1;
                break;
            case 0x00:
                /* MP4/MOV: ....ftyp at offset +4 */
                if (buf[i+4] == 0x66 && buf[i+5] == 0x74 && buf[i+6] == 0x79 && buf[i+7] == 0x70) match = 1;
                break;
            case 0x1A:
                /* MKV: 1A 45 DF A3 */
                if (buf[i+1] == 0x45 && buf[i+2] == 0xDF && buf[i+3] == 0xA3) match = 1;
                break;
            case 0x66:
                /* FLAC: fLaC */
                if (buf[i+1] == 0x4C && buf[i+2] == 0x61 && buf[i+3] == 0x43) match = 1;
                break;
            case 0x37:
                /* 7Z: 37 7A BC AF 27 1C */
                if (buf[i+1] == 0x7A && buf[i+2] == 0xBC && buf[i+3] == 0xAF) match = 1;
                break;
            case 0x1F:
                /* GZIP: 1F 8B 08 */
                if (buf[i+1] == 0x8B && buf[i+2] == 0x08 && (i % 512 == 0)) match = 1;
                break;
            default:
                break;
        }
        if (match) {
            out_offsets[count++] = (int32_t)i;
            if (count >= max_results) {
                break;
            }
        }
    }
    return count;
}
