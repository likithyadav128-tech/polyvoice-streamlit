with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'active_text = "\\n\\n".join' in line or 'active_text = "' in line and '.join' in line:
        new_lines.append("        active_text = '\\n\\n'.join([f'=== {v[\"lang_name\"]} ({k}) ===\\n{v[\"text\"]}' for k, v in st.session_state.translations.items()])\n")
    elif 'srt_data = "' in line and '.join' in line:
        new_lines.append("        srt_data = '\\n'.join(srt_lines)\n")
    elif 'vtt_data = "' in line and '.join' in line:
        new_lines.append("        vtt_data = '\\n'.join(vtt_lines)\n")
    elif 'lrc_data = "' in line and '.join' in line:
        new_lines.append("        lrc_data = '\\n'.join(lrc_lines)\n")
    elif 'return "\\n".join' in line or 'return "' in line and '.join(translated_lines)' in line:
        new_lines.append("    return '\\n'.join(translated_lines)\n")
    else:
        new_lines.append(line)

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("Updated app.py cleanly!")
