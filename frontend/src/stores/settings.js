import { reactive, onMounted } from 'vue';
import { getSettings } from '@/api/settings';

const state = reactive({
  settings: {
    DEMO_MODE: false
  },
  loading: false,
  error: null
});

export function useSettingsStore() {
  const fetchSettings = async () => {
    state.loading = true;
    try {
      const response = await getSettings();
      // Assume the response has the structure where we can find DEMO_MODE
      // Based on L4/L2 backend changes, it might be in different places.
      // We'll normalize it here.
      state.settings = {
        ...state.settings,
        ...response.data
      };
    } catch (err) {
      state.error = err;
      console.error("Failed to fetch settings:", err);
    } finally {
      state.loading = false;
    }
  };

  onMounted(() => {
    if (!state.settings.DEMO_MODE) {
      fetchSettings();
    }
  });

  return {
    settings: state.settings,
    loading: state.loading,
    error: state.error,
    fetchSettings
  };
}
