"use client";

import React, { useEffect, useState } from "react";
import Papa from "papaparse";
import { Menubar, MenubarMenu, MenubarTrigger } from "@/components/ui/menubar";
import Link from "next/link";
import Image from "next/image";

interface ContractMeta {
  "Databento Symbol": string;
  "IB Symbol": string;
  "Name": string;
  "Exchange": string;
  "Intraday Initial Margin": string;
  "Intraday Maintenance Margin": string;
  "Overnight Initial Margin": string;
  "Overnight Maintenance Margin": string;
  "Asset Type": string;
  "Sector": string;
  "Contract Size": string;
  "Units": string;
  "Minimum Price Fluctuation": string;
  "Tick Size": string;
  "Settlement Type": string;
  "Trading Hours (EST)": string;
  "Data Provider": string;
  "Dataset": string;
  "Newest Month Additions": string;
  "Contract Months": string;
  "Time of Expiry": string;
}

const Metadata: React.FC = () => {
  const [contracts, setContracts] = useState<ContractMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const fetchCSV = async () => {
      try {
        // 1. Call the Flask endpoint to ensure the CSV file is written.
        // Adjust the URL as needed.
        await fetch("http://localhost:5000/metadata");

        // 2. After the CSV is written, fetch it from the public folder.
        const response = await fetch("/metadata.csv");
        const csvText = await response.text();

        Papa.parse<ContractMeta>(csvText, {
          header: true,
          skipEmptyLines: true,
          complete: (results) => {
            setContracts(results.data);
            setLoading(false);
          },
        });
      } catch (error) {
        console.error("Error fetching or parsing CSV:", error);
        setLoading(false);
      }
    };

    fetchCSV();
  }, []);

  if (loading) {
    return <div>Loading metadata...</div>;
  }

  // Filter contracts by "Name" or "Databento Symbol"
  const lowerQuery = query.toLowerCase();
  const filteredContracts = contracts.filter((contract) =>
    contract["Name"].toLowerCase().includes(lowerQuery) ||
    contract["Databento Symbol"].toLowerCase().includes(lowerQuery)
  );

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <Menubar className="h-20 px-4 bg-background shadow-sm">
            <MenubarMenu className="flex items-center space-x-4">
              <MenubarTrigger asChild>
                <Link href="/">
                  <Image
                    src="/images/AlgoLogo.png"
                    alt="AlgoLogo"
                    width={60}
                    height={60}
                    loading="eager"
                  />
                </Link>
              </MenubarTrigger>
              <span className="text-3xl font-bold">Glass Factory</span>
            </MenubarMenu>
          </Menubar>
      <div className="mb-4">
        <input
          type="text"
          placeholder="Search by Name or Databento Symbol"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full p-2 border rounded"
        />
      </div>
      {filteredContracts.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredContracts.map((contract, index) => (
            <div key={index} className="border rounded-lg p-4 shadow">
              <h2 className="text-xl font-semibold mb-2">
                {contract["Name"]} ({contract["Databento Symbol"]})
              </h2>
              <p>
                <span className="font-semibold">IB Symbol:</span>{" "}
                {contract["IB Symbol"]}
              </p>
              <p>
                <span className="font-semibold">Exchange:</span>{" "}
                {contract["Exchange"]}
              </p>
              <p>
                <span className="font-semibold">Intraday Initial Margin:</span>{" "}
                {contract["Intraday Initial Margin"]}
              </p>
              <p>
                <span className="font-semibold">
                  Intraday Maintenance Margin:
                </span>{" "}
                {contract["Intraday Maintenance Margin"]}
              </p>
              <p>
                <span className="font-semibold">
                  Overnight Initial Margin:
                </span>{" "}
                {contract["Overnight Initial Margin"]}
              </p>
              <p>
                <span className="font-semibold">
                  Overnight Maintenance Margin:
                </span>{" "}
                {contract["Overnight Maintenance Margin"]}
              </p>
              <p>
                <span className="font-semibold">Asset Type:</span>{" "}
                {contract["Asset Type"]}
              </p>
              <p>
                <span className="font-semibold">Sector:</span>{" "}
                {contract["Sector"]}
              </p>
              <p>
                <span className="font-semibold">Contract Size:</span>{" "}
                {contract["Contract Size"]}
              </p>
              <p>
                <span className="font-semibold">Units:</span>{" "}
                {contract["Units"]}
              </p>
              <p>
                <span className="font-semibold">
                  Minimum Price Fluctuation:
                </span>{" "}
                {contract["Minimum Price Fluctuation"]}
              </p>
              <p>
                <span className="font-semibold">Tick Size:</span>{" "}
                {contract["Tick Size"]}
              </p>
              <p>
                <span className="font-semibold">Settlement Type:</span>{" "}
                {contract["Settlement Type"]}
              </p>
              <p>
                <span className="font-semibold">
                  Trading Hours (EST):
                </span>{" "}
                {contract["Trading Hours (EST)"]}
              </p>
              <p>
                <span className="font-semibold">Data Provider:</span>{" "}
                {contract["Data Provider"]}
              </p>
              <p>
                <span className="font-semibold">Dataset:</span>{" "}
                {contract["Dataset"]}
              </p>
              <p>
                <span className="font-semibold">
                  Newest Month Additions:
                </span>{" "}
                {contract["Newest Month Additions"]}
              </p>
              <p>
                <span className="font-semibold">Contract Months:</span>{" "}
                {contract["Contract Months"]}
              </p>
              <p>
                <span className="font-semibold">Time of Expiry:</span>{" "}
                {contract["Time of Expiry"]}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <div>No contracts found for "{query}".</div>
      )}
    </div>
  );
};

export default Metadata;
