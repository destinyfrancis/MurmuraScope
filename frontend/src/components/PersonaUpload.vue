<template>
  <div class="persona-upload">
    <div class="upload-header">
      <label class="toggle-label">
        <input v-model="enabled" type="checkbox" />
        使用真實受訪者數據初始化 Agents
      </label>
      <span class="hint">支援 CSV / JSON，最多 500 人</span>
    </div>

    <div v-if="enabled" class="upload-body">
      <div
        class="drop-zone"
        :class="{ 'drag-over': dragging }"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
        @click="$refs.fileInput.click()"
      >
        <span v-if="!file">拖放 CSV / JSON 檔案，或點擊上傳</span>
        <span v-else class="file-name">{{ file.name }} ({{ profileCount }} 個 profiles)</span>
        <input ref="fileInput" type="file" accept=".csv,.json" hidden @change="onFileChange" />
      </div>

      <table v-if="preview.length" class="preview-table">
        <thead>
          <tr>
            <th>Name</th><th>Role</th><th>Beliefs</th><th>Goals</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, i) in preview" :key="i">
            <td>{{ p.name }}</td>
            <td>{{ p.role }}</td>
            <td>{{ p.beliefs || '—' }}</td>
            <td>{{ p.goals || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: File, default: null }
})
const emit = defineEmits(['update:modelValue'])

const enabled = ref(false)
const dragging = ref(false)
const file = ref(null)
const preview = ref([])
const profileCount = ref(0)

watch(enabled, (val) => {
  if (!val) {
    file.value = null
    preview.value = []
    profileCount.value = 0
    emit('update:modelValue', null)
  }
})

function onDrop(e) {
  dragging.value = false
  const f = e.dataTransfer.files[0]
  if (f) processFile(f)
}

function onFileChange(e) {
  const f = e.target.files[0]
  if (f) processFile(f)
}

async function processFile(f) {
  file.value = f
  emit('update:modelValue', f)
  const text = await f.text()
  try {
    let rows = []
    if (f.name.endsWith('.json')) {
      rows = JSON.parse(text)
    } else {
      // Simple CSV parse for preview
      const lines = text.trim().split('\n')
      const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''))
      rows = lines.slice(1).map(line => {
        const vals = line.split(',').map(v => v.trim().replace(/^"|"$/g, ''))
        return Object.fromEntries(headers.map((h, i) => [h, vals[i] || '']))
      })
    }
    profileCount.value = rows.length
    preview.value = rows.slice(0, 5)
  } catch {
    preview.value = []
    profileCount.value = 0
  }
}
</script>

<style scoped>
.persona-upload {
  padding: 0.75rem;
  border: 1px dashed #444;
  border-radius: 6px;
  margin-top: 1rem;
}
.upload-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.5rem;
}
.toggle-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-size: 0.9rem;
}
.hint {
  font-size: 0.75rem;
  color: #888;
}
.drop-zone {
  border: 2px dashed #555;
  border-radius: 4px;
  padding: 1.5rem;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s;
  font-size: 0.85rem;
  color: #aaa;
}
.drop-zone.drag-over {
  border-color: #7c3aed;
}
.file-name {
  color: #a78bfa;
}
.preview-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 0.75rem;
  font-size: 0.8rem;
}
.preview-table th,
.preview-table td {
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid #333;
  text-align: left;
}
.preview-table th {
  color: #888;
  font-weight: normal;
}
</style>
