export async function signTypedData(account, typedData) {
  if (!window.ethereum || typeof window.ethereum.request !== "function") {
    throw new Error("A compatible wallet is required to sign this decision.");
  }

  return window.ethereum.request({
    method: "eth_signTypedData_v4",
    params: [account, JSON.stringify(typedData)],
  });
}
