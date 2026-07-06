# Legacy Replica SQL

這個目錄只保存舊 Replica prototype 的 SQL schema 與 seed 資料，供歷史參考。

主流程已改為 `data/*.json -> scripts/import_semantic_map.py -> semantic_map_objects`。
不要將這些 SQL 接回 runtime、測試或部署流程。
