// Step 5: Test Licensing API Endpoint
// This test checks if the API call to /api/licensing/products/ works with auth

// Get the access token from localStorage
var accessToken = localStorage.getItem('access');
console.log('=== Licensing API Test ===');
console.log('Access token exists:', !!accessToken);

if (accessToken) {
  console.log('Access token (first 20 chars):', accessToken.substring(0, 20) + '...');
  
  // Test the API endpoint
  fetch('http://127.0.0.1:8000/api/licensing/products/', {
    method: 'GET',
    headers: {
      'Authorization': 'Bearer ' + accessToken,
      'Content-Type': 'application/json'
    }
  })
  .then(function(response) {
    console.log('API Response Status:', response.status);
    console.log('API Response OK:', response.ok);
    return response.json();
  })
  .then(function(data) {
    console.log('API Response Data:', JSON.stringify(data).substring(0, 200) + '...');
    console.log('=== API Test Complete ===');
  })
  .catch(function(error) {
    console.log('API Error:', error);
    console.log('=== API Test Complete ===');
  });
} else {
  console.log('No access token found - cannot test API');
  console.log('=== API Test Complete ===');
}