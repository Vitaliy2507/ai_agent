import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("config_patcher")


def _traverse_and_set(data: Dict, keys: List[str], value: Any) -> bool:
    """
    Traverse dict using key list and set final value.
    Returns True if successful.
    """
    current = data
    for key in keys[:-1]:
        if key.isdigit() and isinstance(current, list):
            idx = int(key)
            if idx < 0 or idx >= len(current):
                log.error("List index out of range: %s in %s", idx, keys)
                return False
            current = current[idx]
        elif isinstance(current, dict) and key in current:
            current = current[key]
        else:
            log.warning("Path not found during traversal: %s (at '%s')", keys, key)
            return False

    final_key = keys[-1]
    if final_key.isdigit() and isinstance(current, list):
        idx = int(final_key)
        if 0 <= idx < len(current):
            current[idx] = value
            return True
        else:
            log.error("Invalid list index: %s", idx)
            return False
    elif isinstance(current, dict):
        current[final_key] = value
        return True
    else:
        log.error("Cannot assign to scalar context: %s", current)
        return False


class ConfigPatcher:
    def __init__(self, file_path: str):
        self.path = Path(file_path)
        if not self.path.exists():
            raise FileNotFoundError(f"Config file not found: {self.path}")
        self.suffix = self.path.suffix.lower()

    def read(self) -> Dict[str, Any]:
        """Read file into structure. Only JSON is parsed; others return raw lines."""
        text = self.path.read_text(encoding="utf-8")
        if self.suffix == ".json":
            try:
                return json.loads(text)
            except Exception as exc:
                log.error("Invalid JSON in %s: %s", self.path, exc)
                raise
        else:
            # Для .yaml, .yml, .env, .toml — rвернуть список строк для построчного редактирования
            return {"__raw__": text.splitlines()}

    def write(self, data: Dict[str, Any]) -> None:
        """Write data back to file."""
        with self.path.open("w", encoding="utf-8") as fh:
            if self.suffix == ".json":
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            else:
                # Reconstruct from list of lines
                lines = data.get("__raw__", [])
                if isinstance(lines, list):
                    fh.write("\n".join(lines))
                else:
                    fh.write(str(lines))
                if not str(lines).endswith("\n"):
                    fh.write("\n")

    def apply(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply patch using dot notation paths.
        - For .json: uses real dict traversal
        - For others: line-based search/replace using heuristics
        """
        current = self.read()

        if self.suffix == ".json":
            updated = current if isinstance(current, dict) else {}
            success_count = 0
            for dot_path, value in patch.items():
                keys = dot_path.split(".")
                if _traverse_and_set(updated, keys, value):
                    log.info("✅ Set '%s' = %r", dot_path, value)
                    success_count += 1
                else:
                    log.error("❌ Failed to set '%s' = %r", dot_path, value)
            if success_count == 0:
                raise ValueError(f"Could not apply any patch from: {patch}")
            self.write(updated)
            return updated

        elif self.suffix in (".yaml", ".yml", ".env", ".toml", ".ini"):
            if "__raw__" not in current:
                raise RuntimeError(f"Missing __raw__ content in {self.path}")
            result_lines = current["__raw__"][:]

            for dot_path, new_value in patch.items():
                # Используем только последнюю часть пути как ключ
                target_key = dot_path.split(".")[-1]

                found = False
                for i, line in enumerate(result_lines):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or ":" not in line:
                        continue

                    try:
                        key_part, val_part = line.split(":", 1)
                    except ValueError:
                        continue

                    key_name = key_part.strip()

                    # Только точное совпадение ключа
                    if key_name == target_key:
                        # Сохраняем отступ
                        indent = line[: -len(line.lstrip())]

                        # Сохраняем кавычки, если были
                        val_stripped = val_part.lstrip()
                        if val_stripped.startswith(('"', "'")):
                            quote = val_stripped[0]
                            new_quoted = f'{quote}{new_value}{quote}'
                        else:
                            new_quoted = str(new_value)

                        # Пересобираем строку
                        result_lines[i] = f"{indent}{key_name}: {new_quoted}"
                        log.info("✅ Patched '%s' = '%s'", key_name, new_quoted)
                        found = True
                        break  # Только первое совпадение

                if not found:
                    raise ValueError(f"Key '{target_key}' not found in {self.path}")

            current["__raw__"] = result_lines
            self.write(current)
            return current

        else:
            raise RuntimeError(
                f"Unsupported config format: {self.suffix}. "
                "Only .json, .yaml, .yml, .env, .toml, .ini supported."
            )