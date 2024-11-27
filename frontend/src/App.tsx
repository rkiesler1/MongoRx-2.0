import React, { useState } from 'react'
import { spacing } from "@leafygreen-ui/tokens";
import { css } from "@leafygreen-ui/emotion";
import Button from "@leafygreen-ui/button";
import Icon from "@leafygreen-ui/icon";
import {
  SearchInput,
  SearchResult,
  SearchResultGroup
} from "@leafygreen-ui/search-input";
import { Cell, Row, Table, TableBody } from "@leafygreen-ui/table";
import LeafyGreenProvider from "@leafygreen-ui/leafygreen-provider";
import { PageLoader } from "@leafygreen-ui/loading-indicator";
import { Tabs, Tab } from "@leafygreen-ui/tabs";
import { H1, H2, H3, Link } from '@leafygreen-ui/typography';
import './App.css'
import axios from 'axios'

const getBackEndUrl =() => {
  const apiUrl = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';
  return apiUrl
}
function App() {
  const [trials, setTrials] = useState<Trial[]>([]);
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [selected, setSelected] = useState(0);

  interface Trial {
    nct_id: string;
    brief_title: string;
    phase: string;
    status: string;
    enrollment: number;
    condition: string[];
    intervention: string;
    
    // Add other properties as needed
  }
  
  async function getTrialList(url: string, searchParams: any, config: any): Promise<void> {
    // TODO: axios query string parameters
    const response = await axios.get(url + '/trials', config);
    return response.data;
  }
  
  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()    
    try {
      setFormSubmitting(true);  // show page loader
      const config = {
        headers: {
          'content-type': 'application/json',
        },
      };

      const list = await getTrialList(getBackEndUrl(), {}, config);
      setTrials(list);
    } catch (error) {
        console.error('Error:', error);
        // Handle error appropriately - maybe set an error state
    } finally {
        setFormSubmitting(false);
      }
  }  

  return (
    <LeafyGreenProvider>
      <div className="App">
        <div className={css`
          display: grid;
          grid-template-columns: 1fr 2fr 1fr;
          grid-gap: ${spacing[100]}px;
        `}>
          <div>
            <img src="/MongoDB_Logomark_ForestGreen.png" width="20"/>
            <H2>MongoRx</H2>
          </div>
          <form onSubmit={handleSubmit}>
            <SearchInput aria-label="Label">
              <SearchResult
                onClick={() => {
                  console.log("SB: Click Apple");
                }}
                description="This is a description"
              >
                Apple
              </SearchResult>
              <SearchResult>Banana</SearchResult>
              <SearchResult as="a" href="#" description="This is a link">
                Carrot
              </SearchResult>
              <SearchResult description="This is a very very long description. Vivamus sagittis lacus vel augue laoreet rutrum faucibus dolor auctor.">
                Dragonfruit
              </SearchResult>
              <SearchResultGroup label="Peppers">
                <SearchResult description="A moderately hot chili pepper used to flavor dishes">
                  Cayenne
                </SearchResult>
                <SearchResult>Ghost pepper</SearchResult>
                <SearchResult>Habanero</SearchResult>
                <SearchResult>Jalapeño</SearchResult>
                <SearchResult>Red pepper</SearchResult>
                <SearchResult>Scotch bonnet</SearchResult>
              </SearchResultGroup>
            </SearchInput>
            <Button type='submit' rightGlyph={<Icon glyph="MagnifyingGlass" />} variant='primary'>Search</Button>
          </form>
        </div>
        {formSubmitting && (
          <PageLoader description="" />          
        )}
        <div>
          <Tabs
            aria-label="MongoRx Tabs"
            baseFontSize={16}
            setSelected={setSelected}
            selected={selected}
          >
            <Tab name="Dashboard">
              <H1>Dashboard</H1>
            </Tab>
            <Tab name="Trials">
              <H1>Trials</H1>
              <table>
                <tbody>
                  {trials.map((trial, index) => (
                    <tr key={index}>
                      <td>{trial.nct_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Table>
                <TableBody>
                {trials.map((trial, index) => (
                  <Row key={index}>
                    <Cell>{trial.brief_title}</Cell>
                    <Cell>{trial.nct_id}</Cell>
                    <Cell>{trial.phase}</Cell>
                    <Cell>{trial.status}</Cell>
                    <Cell>{trial.enrollment}</Cell>
                    <Cell>{trial.condition}</Cell>
                    <Cell>{trial.intervention}</Cell>
                  </Row>
                  ))}
                </TableBody>
              </Table>
            </Tab>
            <Tab name="Drugs">
              <H1>Drugs</H1>
            </Tab>
          </Tabs>
        </div>
      </div>
    </LeafyGreenProvider>
  );
}

export default App
