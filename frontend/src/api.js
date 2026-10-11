import axios from 'axios';

const api = axios.create({ baseURL: 'http://127.0.0.1:8000/api' });

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem('access');
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

export default api;
