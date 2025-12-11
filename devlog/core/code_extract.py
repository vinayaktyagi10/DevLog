import re
from typing import List, Dict, Optional, Tuple

def extract_functions_from_code(code: str, language: str) -> List[Dict]:
    """
    Extract function/method definitions from code

    Returns list of dicts with:
        - name: function name
        - code: function code
        - start_line: line number where function starts
        - end_line: line number where function ends
    """
    if language == 'python':
        return extract_python_functions(code)
    elif language in ['javascript', 'typescript']:
        return extract_js_functions(code)
    elif language == 'java':
        return extract_java_functions(code)
    elif language in ['c', 'cpp']:
        return extract_c_functions(code)
    elif language == 'go':
        return extract_go_functions(code)
    else:
        # For unsupported languages, return the whole code as one block
        return [{
            'name': 'code_block',
            'code': code,
            'start_line': 1,
            'end_line': len(code.splitlines())
        }]

def extract_python_functions(code: str) -> List[Dict]:
    """Extract Python function and class definitions"""
    functions = []
    lines = code.splitlines()

    # Regex for function/class definitions
    func_pattern = re.compile(r'^(\s*)(def|class)\s+(\w+)')

    i = 0
    while i < len(lines):
        match = func_pattern.match(lines[i])
        if match:
            indent = len(match.group(1))
            func_type = match.group(2)  # 'def' or 'class'
            name = match.group(3)

            # Find the end of this function/class
            start = i
            i += 1

            # Skip to next line with same or less indentation
            while i < len(lines):
                line = lines[i]
                if line.strip() == '':
                    i += 1
                    continue

                # Check indentation
                current_indent = len(line) - len(line.lstrip())
                if line.strip() and current_indent <= indent:
                    break
                i += 1

            end = i
            func_code = '\n'.join(lines[start:end])

            functions.append({
                'name': f"{func_type} {name}",
                'code': func_code,
                'start_line': start + 1,
                'end_line': end
            })
        else:
            i += 1

    return functions

def extract_js_functions(code: str) -> List[Dict]:
    """Extract JavaScript/TypeScript functions"""
    functions = []
    lines = code.splitlines()

    # Patterns for different function styles
    patterns = [
        re.compile(r'^\s*(function\s+\w+)'),           # function name()
        re.compile(r'^\s*(const|let|var)\s+(\w+)\s*=\s*function'),  # const x = function
        re.compile(r'^\s*(const|let|var)\s+(\w+)\s*=\s*\('),        # const x = () =>
        re.compile(r'^\s*(async\s+)?(\w+)\s*\([^)]*\)\s*{'),        # method()
    ]

    i = 0
    while i < len(lines):
        line = lines[i]
        matched = False

        for pattern in patterns:
            match = pattern.search(line)
            if match:
                start = i
                name = match.group(1) if len(match.groups()) == 1 else match.group(2)

                # Find matching closing brace
                brace_count = line.count('{') - line.count('}')
                i += 1

                while i < len(lines) and brace_count > 0:
                    brace_count += lines[i].count('{') - lines[i].count('}')
                    i += 1

                end = i
                func_code = '\n'.join(lines[start:end])

                functions.append({
                    'name': name,
                    'code': func_code,
                    'start_line': start + 1,
                    'end_line': end
                })
                matched = True
                break

        if not matched:
            i += 1

    return functions

def extract_java_functions(code: str) -> List[Dict]:
    """Extract Java methods and classes"""
    functions = []
    lines = code.splitlines()

    # Pattern for methods and classes
    pattern = re.compile(r'^\s*(public|private|protected)?\s*(static)?\s*(class|\w+)\s+(\w+)\s*[\(\{]')

    i = 0
    while i < len(lines):
        match = pattern.search(lines[i])
        if match:
            name = match.group(4)
            start = i

            # Find matching closing brace
            brace_count = lines[i].count('{') - lines[i].count('}')
            i += 1

            while i < len(lines) and brace_count > 0:
                brace_count += lines[i].count('{') - lines[i].count('}')
                i += 1

            end = i
            func_code = '\n'.join(lines[start:end])

            functions.append({
                'name': name,
                'code': func_code,
                'start_line': start + 1,
                'end_line': end
            })
        else:
            i += 1

    return functions

def extract_c_functions(code: str) -> List[Dict]:
    """Extract C/C++ functions"""
    functions = []
    lines = code.splitlines()

    # Simple pattern for function definitions
    # This won't catch all cases but works for common patterns
    pattern = re.compile(r'^\s*[\w\*\s]+\s+(\w+)\s*\([^)]*\)\s*{')

    i = 0
    while i < len(lines):
        match = pattern.search(lines[i])
        if match:
            name = match.group(1)
            start = i

            # Find matching closing brace
            brace_count = lines[i].count('{') - lines[i].count('}')
            i += 1

            while i < len(lines) and brace_count > 0:
                brace_count += lines[i].count('{') - lines[i].count('}')
                i += 1

            end = i
            func_code = '\n'.join(lines[start:end])

            functions.append({
                'name': name,
                'code': func_code,
                'start_line': start + 1,
                'end_line': end
            })
        else:
            i += 1

    return functions

def extract_go_functions(code: str) -> List[Dict]:
    """Extract Go functions"""
    functions = []
    lines = code.splitlines()

    pattern = re.compile(r'^\s*func\s+(\w+|\(\w+\s+\*?\w+\)\s+\w+)\s*\(')

    i = 0
    while i < len(lines):
        match = pattern.search(lines[i])
        if match:
            name = match.group(1)
            start = i

            # Find matching closing brace
            brace_count = lines[i].count('{') - lines[i].count('}')
            i += 1

            while i < len(lines) and brace_count > 0:
                brace_count += lines[i].count('{') - lines[i].count('}')
                i += 1

            end = i
            func_code = '\n'.join(lines[start:end])

            functions.append({
                'name': name,
                'code': func_code,
                'start_line': start + 1,
                'end_line': end
            })
        else:
            i += 1

    return functions

def extract_changed_functions(diff_text: str, code_after: str, language: str) -> List[Dict]:
    """
    Extract only the functions that were actually changed in a diff

    Args:
        diff_text: The git diff
        code_after: The full code after changes
        language: Programming language

    Returns:
        List of changed functions with context
    """
    # Parse diff to find changed line numbers
    changed_lines = set()

    for line in diff_text.splitlines():
        if line.startswith('@@'):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            match = re.search(r'\+(\d+),?(\d+)?', line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2)) if match.group(2) else 1
                changed_lines.update(range(start, start + count))

    # Extract all functions
    all_functions = extract_functions_from_code(code_after, language)

    # Filter to only functions that overlap with changed lines
    changed_functions = []
    for func in all_functions:
        func_lines = set(range(func['start_line'], func['end_line'] + 1))
        if func_lines & changed_lines:  # Intersection
            func['changed_lines'] = sorted(func_lines & changed_lines)
            changed_functions.append(func)

    return changed_functions

def get_code_summary(code: str, language: str) -> str:
    """Generate a brief summary of what the code does"""
    functions = extract_functions_from_code(code, language)

    if not functions:
        lines = len(code.splitlines())
        return f"{lines} lines of {language} code"

    func_names = [f['name'] for f in functions]
    return f"{len(functions)} {language} functions: {', '.join(func_names[:5])}" + \
           (f" and {len(func_names) - 5} more" if len(func_names) > 5 else "")
