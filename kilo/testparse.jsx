function Foo({ action }) {
  const [loadingRefs, setLoadingRefs] = useState(false);
  useEffect(() => {
    if (action !== 'issue') return;
    setLoadingRefs(true);
    Promise.all([
      api.get('/accounts/users/').then((r) => setUsers(r.data.results ?? r.data ?? [])).catch(() => setUsers([])),
      api.get('/accounts/departments/').then((r) => setDepts(r.data.results ?? r.data ?? [])).catch(() => setDepts([])),
    ]);
  }, [action]);
}
